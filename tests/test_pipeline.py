"""
End-to-end pipeline tests: real nodes, real agents, real prompts, scripted model.

    python -m pytest tests/test_pipeline.py -v

`tests/test_graph_topology.py` proves the graph is wired correctly. This file proves the
pipeline produces a *decision* -- prompt construction, JSON parsing, citation filtering,
reconciliation, confidence composition and validation all run for real.
"""

from __future__ import annotations

import pytest

from src.graph import nodes as node_mod
from src.graph.graph_state import initial_state, new_run_id
from src.graph.support_graph import walk_graph
from src.utils import llm as llm_mod
from src.utils.config import app_config, resolve
from src.utils.schemas import load_tickets
from tests.fake_llm import scripted_client

TICKETS = "data/tickets/synthetic_tickets.json"


@pytest.fixture(scope="module")
def tickets():
    return {t.ticket_id: t for t in load_tickets(resolve(TICKETS))}


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    from src.memory.customer_thread_store import CustomerThreadStore
    from src.retrieval.bm25 import BM25Index
    from src.retrieval.retriever import Retriever
    from src.utils.config import routing_rules

    CustomerThreadStore.reset_default()
    monkeypatch.setitem(
        app_config()["outputs"], "customer_threads", str(tmp_path / "threads.jsonl")
    )
    node_mod._audit_loggers.clear()
    # BM25 needs no index, no torch and no network, so the retrieval half is real too.
    node_mod.set_retriever(
        Retriever(BM25Index.from_knowledge_base(), k=5, similarity_floor=0.0,
                  routing_rules=routing_rules())
    )
    yield
    CustomerThreadStore.reset_default()
    node_mod.set_retriever(None)
    llm_mod.set_default_client(None)


def run(ticket, tmp_path, **transport_kwargs):
    llm_mod.set_default_client(scripted_client(tmp_path, **transport_kwargs))
    from src.logging.audit_logger import AuditLogger

    state = initial_state(ticket, run_id=new_run_id())
    node_mod.set_audit_logger(state["run_id"], AuditLogger(state["run_id"], directory=tmp_path))
    return walk_graph(dict(state), trace_path=True)


# ------------------------------------------------------------------------------ happy path


def test_a_fee_ticket_flows_end_to_end(tickets, tmp_path):
    """TCK-1143: no prior reversal, fee 7 days old. The textbook FEE-001 courtesy reversal."""
    state, path = run(tickets["TCK-1143"], tmp_path)

    assert path[-1] == "audit_log"
    assert state["route"] == "AUTO_RESOLVE"
    assert state["rule_route"] == "AUTO_RESOLVE"  # rules got there independently
    assert state["llm_route"] == "AUTO_RESOLVE"
    assert "FEE-001" in state["cited_policy_ids"]
    assert state["validation"].ok
    assert state["confidence"] > 0.7


def test_the_model_is_never_shown_the_rule_engines_answer(tickets, tmp_path):
    """
    D4's whole value is two independent opinions. Leaking `rule_route` into the routing prompt
    turns the second opinion into agreement and the disagreement signal disappears.
    """
    llm_mod.set_default_client(scripted_client(tmp_path))
    client = llm_mod.default_client()
    run(tickets["TCK-1143"], tmp_path)
    routing_prompts = [
        c["prompt"] for c in llm_mod.default_client()._transport.calls if c["kind"] == "routing"
    ]
    assert routing_prompts
    for prompt in routing_prompts:
        assert "rule_route" not in prompt
        assert "deterministic rule" not in prompt.lower()


def test_preconditions_reach_the_prompts_as_established_fact(tickets, tmp_path):
    """
    HLD D2. The message says "I don't think I've ever asked before"; the record agrees here,
    but the model must be reading the record, not the sentence.
    """
    run(tickets["TCK-1143"], tmp_path)
    analysis_prompts = [
        c["prompt"] for c in llm_mod.default_client()._transport.calls if c["kind"] == "analysis"
    ]
    assert analysis_prompts
    assert "no_prior_fee_reversal_12m" in analysis_prompts[0]
    assert "established fact" in analysis_prompts[0]


# --------------------------------------------------------------------------- the safety path


def test_a_threat_takes_the_bypass_with_no_policy_in_context(tickets, tmp_path):
    """
    TCK-1019. The assertion that matters is the empty context: a crisis reply must not be
    drafted with fee clauses sitting in the window.
    """
    state, path = run(tickets["TCK-1019"], tmp_path)

    assert "retrieve" not in path
    assert state["retrieved"] == []
    assert state["context_block"] == ""
    assert state["route"] == "ESCALATE"  # never REFUSE
    assert state["escalation_target"] == "Threat Response"
    # No model call at all on this path -- the reply is fixed text.
    assert not any(c["kind"] == "drafting" for c in llm_mod.default_client()._transport.calls)


def test_a_hostile_but_legitimate_ticket_does_not_take_the_bypass(tickets, tmp_path):
    """TCK-1077 threatens to post on Twitter. That is a lawful remedy, not a safety concern."""
    state, path = run(tickets["TCK-1077"], tmp_path)
    assert "safety_escalate" not in path
    assert "retrieve" in path
    assert state["route"] != "REFUSE"


def test_a_silent_referral_is_never_named_in_the_draft(tickets, tmp_path):
    """
    TCK-1078. Naming a Conduct Review referral warns the person the account holder may need
    protecting from, so `validate_draft` treats it as a violation.
    """
    state, _ = run(
        tickets["TCK-1078"],
        tmp_path,
        drafting={
            "body": "I've referred this to our Conduct Review team.",
            "cited_policy_ids": [],
        },
    )
    assert state["escalation_visible_to_customer"] is False
    assert state["escalation_target"] == "Conduct Review"
    assert any("invisible" in v for v in state["validation"].violations)


def test_an_elder_abuse_victim_is_escalated_not_refused(tickets, tmp_path):
    """
    TCK-1055: an 81-year-old reporting her daughter. Superficially a third-party access
    pattern, actually a DSP-003 dispute. Refusing her is the worst outcome available.
    """
    state, _ = run(tickets["TCK-1055"], tmp_path)
    assert state["route"] == "ESCALATE"
    assert state["rule_route"] == "ESCALATE"
    assert state["escalation_target"] == "Claims Specialist"


# ----------------------------------------------------------------------- hallucination guard


def test_a_clause_that_was_never_retrieved_cannot_be_cited(tickets, tmp_path):
    """
    Filtered at the source in `agents.policy.analyse`, so it never reaches the draft. P4's
    gate is zero hallucinated citations, and the cheapest way to hit zero is to make the
    invalid citation unrepresentable.
    """
    state, _ = run(
        tickets["TCK-1143"],
        tmp_path,
        analysis={
            "deciding_clauses": [
                {"policy_id": "FEE-001", "why": "real"},
                {"policy_id": "FEE-999", "why": "invented"},
            ],
            "constraining_clauses": [],
            "missing_facts": [],
            "policy_verified": True,
            "conflicts": [],
            "self_certainty": 0.9,
        },
    )
    assert "FEE-999" not in state["policy_analysis"].deciding_ids()
    assert state["validation"].hallucinated_citations == []


def test_prohibited_content_in_a_draft_is_caught(tickets, tmp_path):
    state, _ = run(
        tickets["TCK-1143"],
        tmp_path,
        drafting={
            "body": "I guarantee your refund will appear within 3 business days.",
            "cited_policy_ids": [],
        },
    )
    assert not state["validation"].ok
    assert any("promises an outcome" in v for v in state["validation"].violations)


# --------------------------------------------------------------------------- robustness


def test_a_malformed_response_is_repaired_not_fatal(tickets, tmp_path):
    """One bad JSON body per agent, then a correct one. The run must not notice."""
    state, path = run(
        tickets["TCK-1143"], tmp_path, malformed={"triage", "analysis", "routing", "drafting"}
    )
    assert path[-1] == "audit_log"
    assert state["route"] in {"AUTO_RESOLVE", "ESCALATE", "REFUSE", "ASK_MORE_INFO"}


def test_a_total_model_outage_degrades_to_escalation(tickets, tmp_path):
    """
    Groq down, key missing, quota gone. Every ticket must still reach a human with a complete
    audit record -- never a guess, never a crash.
    """
    state, path = run(
        tickets["TCK-1143"],
        tmp_path,
        raise_on={"triage", "analysis", "routing", "drafting"},
    )
    assert path[-1] == "audit_log"
    assert state["route"] == "ESCALATE"
    assert state["draft"]  # a bare acknowledgement, not an empty string
    assert any("degraded" in note or "unavailable" in note for note in state["notes"])


def test_retrieval_still_runs_when_the_model_is_down(tickets, tmp_path):
    """Retrieval needs no model, so a model outage must not cost us the evidence trail."""
    state, _ = run(tickets["TCK-1143"], tmp_path, raise_on={"triage", "analysis", "routing"})
    assert state["retrieved"]
    assert state["retrieval_log"]


# ------------------------------------------------------------------------------- the loops


def test_disagreement_holds_at_escalate_and_triggers_the_recheck_loop(tickets, tmp_path):
    """
    Rules say AUTO_RESOLVE, the model says REFUSE. That gap is the hard-case detector: the
    ticket holds at ESCALATE and the confidence loop gets a chance to look again.
    """
    state, path = run(
        tickets["TCK-1143"],
        tmp_path,
        routing={"route": "REFUSE", "rationale": "scripted disagreement",
                 "escalation_target": None},
    )
    assert state["rule_route"] == "AUTO_RESOLVE"
    assert state["llm_route"] == "REFUSE"
    assert state["route"] == "ESCALATE"
    assert "disagreement" in state["route_rationale"]
    assert state["confidence_parts"]["route_agreement"] == 0.0


def test_unverified_policy_escalates_after_the_refinement_loop(tickets, tmp_path):
    state, path = run(
        tickets["TCK-1143"],
        tmp_path,
        analysis={
            "deciding_clauses": [],
            "constraining_clauses": [],
            "missing_facts": [],
            "policy_verified": False,
            "conflicts": [],
            "self_certainty": 0.2,
        },
    )
    cap = app_config()["graph"]["loop_caps"]["retrieval_refine"]
    assert path.count("retrieve") == cap
    assert state["route"] == "ESCALATE"
    assert "retrieval_refine" in state["loops_capped"]


def test_a_repair_pass_tells_the_model_what_was_wrong(tickets, tmp_path):
    """A retry that changes nothing returns the same draft and spends the budget for free."""
    state, _ = run(
        tickets["TCK-1143"],
        tmp_path,
        drafting={"body": "I guarantee this refund.", "cited_policy_ids": []},
    )
    drafting_prompts = [
        c["prompt"] for c in llm_mod.default_client()._transport.calls if c["kind"] == "drafting"
    ]
    assert len(drafting_prompts) >= 2
    assert "PREVIOUS DRAFT WAS REJECTED" in drafting_prompts[-1]


# ------------------------------------------------------------------------------ audit trail


def test_the_audit_record_holds_the_evidence_not_just_the_verdict(tickets, tmp_path):
    import glob
    import json

    run(tickets["TCK-1143"], tmp_path)
    # run_*.jsonl specifically -- the thread store also writes a .jsonl into tmp_path.
    record = json.loads(open(glob.glob(str(tmp_path / "run_*.jsonl"))[0]).readline())

    assert record["route"] and record["route_rationale"]
    assert record["rule_route"] and record["llm_route"]  # both proposals kept
    assert record["retrieval_log"]  # every attempt, not just the last
    assert record["confidence_parts"]
    # A precondition's inputs, not only its verdict: "eligible" is an assertion,
    # "eligible -- no prior reversal in 12 months" is evidence.
    reversal = record["preconditions"]["no_prior_fee_reversal_12m"]
    assert reversal["inputs"]["prior_fee_reversals_12m"] == 0
    assert record["config_hash"]
