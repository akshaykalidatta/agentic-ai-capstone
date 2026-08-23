"""
Topology tests. These run with no langgraph, chromadb or torch installed -- the properties
checked here belong to the tables in `edges.py`, not to the framework.

    python -m pytest tests/test_graph_topology.py -v

The three loop tests are the ones to read. Each drives a loop to its cap and asserts the
documented exit -- not just "it stopped", but "it stopped, escalated, and recorded that it
did". "It terminated" is satisfied by a crash.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.graph import nodes as node_mod
from src.graph.edges import (
    CONDITIONAL_EDGES,
    EDGES,
    LOOPS,
    ROUTERS,
    after_analysis,
    after_confidence,
    after_review,
    after_triage,
    after_validation,
)
from src.graph.graph_state import initial_state, new_run_id
from src.graph.nodes import NODES
from src.graph.support_graph import END, START, StepLimitExceeded, merge_state_update, walk_graph
from src.utils.constants import NODE_NAMES
from src.utils.config import app_config, resolve
from src.utils.schemas import ValidationResult, load_tickets

SAMPLE = "data/tickets/sample_ticket_batch.json"


# ------------------------------------------------------------------------------ fixtures


@dataclass
class FakeHit:
    """Duck-types `src.retrieval.retriever.Hit`. Structural typing, no import needed."""

    chunk_id: str = "refund_policy::FEE-001"
    policy_id: str = "FEE-001"
    source_file: str = "refund_policy.md"
    chunk_type: str = "clause"
    section: str = "2. Fee reversals (FEE)"
    title: str = "One-time courtesy reversal"
    text: str = "A single overdraft fee may be reversed once per rolling 12 months."
    similarity: float = 0.71
    citable: bool = True
    injected: bool = False


@dataclass
class FakeResult:
    hits: list = field(default_factory=list)
    top_similarity: float = 0.0
    below_floor: bool = True
    scope_signal: bool = False

    def policy_ids(self, **_):
        return [h.policy_id for h in self.hits if h.policy_id]

    def source_files(self):
        return list(dict.fromkeys(h.source_file for h in self.hits))

    def context_block(self, **_):
        return "\n".join(f"[{h.policy_id}] {h.text}" for h in self.hits)


class FakeRetriever:
    """
    Returns one citable clause -- enough for `analyse_policy`'s proxy to call policy verified,
    which is what lets the other two loops be reached. Injected via `nodes.set_retriever`.
    """

    mode = "fake"

    def retrieve(self, query, **_):
        return FakeResult(hits=[FakeHit()], top_similarity=0.71, below_floor=False)


class EmptyRetriever(FakeRetriever):
    """Returns nothing. Drives the retrieval-refinement loop to its cap."""

    mode = "empty"

    def retrieve(self, query, **_):
        return FakeResult(hits=[], top_similarity=0.0, below_floor=True)


@pytest.fixture
def ticket():
    return load_tickets(resolve(SAMPLE))[0]


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """
    Temp directories and fresh singletons. Without this the thread-store singleton carries
    state between tests, so test 4 sees case history written by test 2.
    """
    from src.memory.customer_thread_store import CustomerThreadStore

    CustomerThreadStore.reset_default()
    monkeypatch.setitem(app_config()["outputs"], "customer_threads", str(tmp_path / "threads.jsonl"))
    node_mod._audit_loggers.clear()
    node_mod.set_retriever(FakeRetriever())
    yield
    CustomerThreadStore.reset_default()
    node_mod.set_retriever(None)


def run(ticket, **stubs):
    # no_model=True: these tests are about topology, so every node takes its deterministic
    # path. The agents' own behaviour is covered by tests/test_pipeline.py against a
    # scripted model.
    state = initial_state(ticket, run_id=new_run_id(), stubs=stubs or {}, no_model=True)
    from src.logging.audit_logger import AuditLogger

    node_mod.set_audit_logger(state["run_id"], AuditLogger(state["run_id"], directory=None))
    return walk_graph(dict(state), trace_path=True)


# ------------------------------------------------------------------- structural invariants


def test_node_registry_matches_constants():
    """A node in one list and not the other is a silently unreachable node."""
    assert set(NODES) == set(NODE_NAMES)


def test_every_node_is_reachable():
    destinations = {d for _, d in EDGES} | {
        d for m in CONDITIONAL_EDGES.values() for d in m.values()
    }
    assert set(NODES) - destinations == set()


def test_every_router_destination_exists():
    """LangGraph has no default edge: an unmapped key raises at runtime, on ticket 94 of 150."""
    for source, mapping in CONDITIONAL_EDGES.items():
        assert source in NODES
        for key, destination in mapping.items():
            assert destination in NODES, f"{source}[{key}] -> {destination} does not exist"


def test_routers_cover_their_mappings():
    """Every literal a router returns must appear in its mapping, or LangGraph raises."""
    cases = {
        "triage": [({"safety_flags": []}, "normal"), ({"safety_critical": True}, "safety")],
        "analyse_policy": [({"retrieval_attempts": 9}, "route")],
        "score_confidence": [({"route": "AUTO_RESOLVE", "confidence": 0.99}, "draft")],
        "validate_draft": [({"validation": ValidationResult(ok=True)}, "review")],
        "hitl_gate": [({"reviewer": None}, "done")],
    }
    for source, pairs in cases.items():
        for state, expected in pairs:
            key = ROUTERS[source](state)
            assert key == expected
            assert key in CONDITIONAL_EDGES[source]

    # Called directly too, so a router accidentally dropped from ROUTERS is still covered.
    assert after_triage({"safety_critical": True}) == "safety"
    assert after_analysis({"retrieval_attempts": 0}) == "refine"
    assert after_confidence({"route": "AUTO_RESOLVE", "confidence": 0.1}) == "reconsider"
    assert after_validation({"validation": ValidationResult(ok=False, violations=["x"])}) == "repair"
    assert after_review({}) == "done"


def test_start_and_end_are_wired():
    plain = dict(EDGES)
    assert plain[START] == "triage"
    assert plain["audit_log"] == END


def test_every_loop_has_a_declared_exit():
    for loop in LOOPS:
        mapping = CONDITIONAL_EDGES[loop["router"]]
        assert mapping[loop["exit_key"]] == loop["exit_node"]
        # The exit must not be the loop's own back edge.
        assert loop["exit_node"] != loop["back_edge"][1]


# ------------------------------------------------------------------------- reducer semantics


def test_additive_keys_concatenate_and_others_overwrite():
    """`trace` and `notes` grow; `route` replaces. The most common LangGraph bug, pinned."""
    state = {"trace": [], "notes": ["a"], "route": "ESCALATE"}
    merged = merge_state_update(state, {"notes": ["b"], "route": "REFUSE"})
    assert merged["notes"] == ["a", "b"]
    assert merged["route"] == "REFUSE"


# ------------------------------------------------------------------------------ happy path


def test_happy_path_reaches_audit(ticket):
    state, path = run(ticket)
    assert path[0] == "triage"
    assert path[-1] == "audit_log"
    assert state["route"] in {"AUTO_RESOLVE", "ESCALATE", "REFUSE", "ASK_MORE_INFO"}
    assert state["reviewer"] is not None
    # No loop should fire on a clean ticket: one pass through each node.
    assert path.count("retrieve") == 1
    assert path.count("draft_reply") == 1
    assert state["loops_capped"] == []


def test_trace_records_every_node_once_per_execution(ticket):
    state, path = run(ticket)
    assert [t.node for t in state["trace"]] == path


# --------------------------------------------------------------------- the safety bypass


def test_safety_critical_bypasses_retrieval_entirely(ticket):
    """
    The assertion that matters is not "it escalated" but that no KB text is in context -- what
    stops "I'm sorry to hear that. Regarding your $35 overdraft fee, under FEE-001...".
    """
    state, path = run(ticket, safety_flags=[{"code": "SELF_HARM", "severity": "critical"}])
    assert "retrieve" not in path
    assert "preconditions" not in path
    assert state["retrieved"] == []
    assert state["context_block"] == ""
    assert state["retrieval_mode"] == "bypassed"
    assert state["route"] == "ESCALATE"  # never REFUSE
    assert state["escalation_target"] == "Vulnerable Customer Support"
    assert path[-1] == "audit_log"  # the bypass still passes through review


def test_silent_escalation_is_not_visible_to_the_customer(ticket):
    """
    TCK-1078's shape: refuse the access request *and* refer, with the reply giving no sign.

    The silent code is THIRD_PARTY_ACCESS, not FINANCIAL_ABUSE. The dataset forced that split:
    FINANCIAL_ABUSE is a customer reporting exploitation of their own account (TCK-1055, a
    visible escalation to Claims Specialist), while THIRD_PARTY_ACCESS is someone asking for
    an account they are not on -- possibly the abuser.
    """
    state, _ = run(ticket, safety_flags=[{"code": "THIRD_PARTY_ACCESS", "severity": "high"}])
    assert state["escalation_target"] == "Conduct Review"
    assert state["escalation_visible_to_customer"] is False

    visible, _ = run(ticket, safety_flags=[{"code": "FINANCIAL_ABUSE", "severity": "high"}])
    assert visible["escalation_target"] == "Claims Specialist"
    assert visible["escalation_visible_to_customer"] is True


def test_tone_alone_never_takes_the_bypass(ticket):
    """
    The headline failure mode. An angry customer with a legitimate request is routed on the
    *request*; tone changes the drafting register and nothing else.
    """
    state, path = run(ticket, sentiment="angry")
    assert "safety_escalate" not in path
    assert "retrieve" in path


# ------------------------------------------------------------------------------- loop 1


def test_retrieval_loop_caps_and_escalates(ticket):
    """Cap 2 = two retrievals, one refinement, then ESCALATE on unverified policy."""
    node_mod.set_retriever(EmptyRetriever())
    state, path = run(ticket)
    cap = app_config()["graph"]["loop_caps"]["retrieval_refine"]

    assert path.count("retrieve") == cap
    assert path.count("refine_query") == cap - 1
    assert state["retrieval_attempts"] == cap
    assert state["policy_analysis"].policy_verified is False
    assert state["route"] == "ESCALATE"
    assert "retrieval_refine" in state["loops_capped"]
    # Recorded once, not once per pass -- the reducer would happily duplicate it.
    assert state["loops_capped"].count("retrieval_refine") == 1
    # Every attempt logged, not just the last.
    assert [a.attempt for a in state["retrieval_log"]] == list(range(1, cap + 1))


def test_refinement_changes_the_query(ticket):
    """`lld_notes.md` 1.3: an identical retry is a wasted call that returns an identical answer."""
    node_mod.set_retriever(EmptyRetriever())
    state, _ = run(ticket, missing_facts=["was the merchant contacted"])
    first, second = state["retrieval_log"][0], state["retrieval_log"][1]
    assert first.query != second.query
    assert "merchant" in second.query


# ------------------------------------------------------------------------------- loop 2


def test_confidence_loop_caps_and_escalates(ticket):
    """Confidence pinned below every floor. Must resolve upward, never toward AUTO_RESOLVE."""
    cap = app_config()["graph"]["loop_caps"]["confidence_recheck"]
    state, path = run(ticket, confidence=0.10, llm_route="AUTO_RESOLVE")

    assert path.count("score_confidence") == cap
    # One first pass plus one per reconsider: `cap` rechecks means `cap - 1` reconsiders.
    assert path.count("analyse_policy") == cap
    assert state["route"] == "ESCALATE"
    assert "confidence_recheck" in state["loops_capped"]
    assert path[-1] == "audit_log"


def test_capped_confidence_prefers_ask_more_info_when_facts_are_missing(ticket):
    """
    Missing facts -> ASK_MORE_INFO. Escalating a ticket we have not finished asking about
    sends a human a question the customer could have answered.
    """
    state, _ = run(ticket, confidence=0.10, missing_facts=["date the transfer was initiated"])
    assert state["route"] == "ASK_MORE_INFO"


def test_confidence_loop_does_not_fire_when_in_band(ticket):
    state, path = run(ticket, confidence=0.95, llm_route="AUTO_RESOLVE")
    assert path.count("score_confidence") == 1
    assert state["loops_capped"] == []


# ------------------------------------------------------------------------------- loop 3


def test_draft_repair_loop_caps_and_escalates(ticket):
    """A draft that fails validation twice is replaced, not shipped."""
    cap = app_config()["graph"]["loop_caps"]["draft_repair"]
    state, path = run(ticket, violations=["promises a specific resolution date"])

    assert path.count("draft_reply") == cap
    assert path.count("validate_draft") == cap
    assert state["route"] == "ESCALATE"
    assert "draft_repair" in state["loops_capped"]
    assert state["cited_policy_ids"] == []
    assert path[-1] == "audit_log"


def test_hallucinated_citation_is_caught_mechanically(ticket):
    """A cited ID is in the retrieved set or it is not -- which is why P4's gate can be zero."""
    state = initial_state(ticket, run_id="t")
    state = merge_state_update(dict(state), {"retrieved": [], "cited_policy_ids": ["FEE-009"]})
    update = node_mod.validate_draft(state)
    assert update["validation"].hallucinated_citations == ["FEE-009"]
    assert update["validation"].is_hard_failure


def test_citing_an_internal_clause_is_a_distinct_failure(ticket):
    """CON-010 is retrievable, injectable and never quotable. Different mistake, different list."""
    from src.utils.schemas import RetrievedChunk

    state = initial_state(ticket, run_id="t")
    state = merge_state_update(
        dict(state),
        {
            "retrieved": [RetrievedChunk(chunk_id="c", policy_id="CON-010", citable=False)],
            "cited_policy_ids": ["CON-010"],
        },
    )
    update = node_mod.validate_draft(state)
    assert update["validation"].uncitable_citations == ["CON-010"]
    assert update["validation"].hallucinated_citations == []


# ------------------------------------------------------------------- review re-entry & bounds


def test_regeneration_re_enters_drafting_and_still_terminates(ticket):
    """The one action that re-enters the graph. It must not create a fourth, undeclared loop."""
    state, path = run(ticket)
    assert path[-1] == "audit_log"
    assert after_review({"reviewer": state["reviewer"]}) == "done"

    from src.utils.schemas import ReviewerDecision

    regen = ReviewerDecision(action="REQUEST_REGENERATION")
    assert after_review({"reviewer": regen}) == "regenerate"


def test_worst_case_path_fits_inside_the_recursion_limit(ticket):
    """
    Every loop capped on one ticket. If this exceeds `recursion_limit`, a real run dies partway
    through the queue -- which is why the limit is counted from a worst case, not picked.
    """
    node_mod.set_retriever(FakeRetriever())
    state, path = run(
        ticket,
        confidence=0.10,
        violations=["promises a specific resolution date"],
    )
    limit = app_config()["graph"]["recursion_limit"]
    assert len(path) < limit, f"worst case {len(path)} nodes vs limit {limit}"
    assert path[-1] == "audit_log"
    assert set(state["loops_capped"]) >= {"confidence_recheck", "draft_repair"}


def test_step_limit_raises_rather_than_hanging(ticket):
    state = initial_state(ticket, run_id="t")
    with pytest.raises(StepLimitExceeded):
        walk_graph(dict(state), max_steps=3)
