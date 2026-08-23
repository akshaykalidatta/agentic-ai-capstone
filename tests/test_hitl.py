"""
P7: suspend, resume, and the six reviewer actions.

    python -m pytest tests/test_hitl.py -v

No API key and no built index: the model is `tests/fake_llm.ScriptedTransport` and retrieval is
BM25 over `data/knowledge_base/`, both of which run on a bare checkout.

The test to read first is `test_a_suspended_review_survives_a_process_restart`. It is the
phase's gate, and everything else here is only meaningful if it passes -- a review surface that
loses its queue when Streamlit reloads is a demo, not a gate.
"""

from __future__ import annotations

import gc
import json
import sqlite3

import pytest

pytest.importorskip(
    "langgraph.checkpoint.sqlite",
    reason="P7 needs langgraph-checkpoint-sqlite: pip install -r requirements.txt",
)

from langgraph.types import Command  # noqa: E402

from src.graph import nodes as node_mod  # noqa: E402
from src.graph.checkpointing import (  # noqa: E402
    JsonMetadataSerializer,
    repair_metadata_serializer,
    sqlite_saver,
)
from src.graph.graph_state import initial_state, new_run_id, review_payload  # noqa: E402
from src.graph.support_graph import build_graph, walk_graph  # noqa: E402
from src.hitl.approval_queue import ApprovalQueue, QueueEntry, fold_pending  # noqa: E402
from src.hitl.review_service import (  # noqa: E402
    InteractiveReviewUnavailable,
    PendingReview,
    ReviewService,
    edit_size,
    filter_pending,
    interrupt_values,
    require_durable_checkpointer,
    review_metrics,
    split_by_agreement,
)
from src.utils import llm as llm_mod  # noqa: E402
from src.utils.config import app_config, resolve, routing_rules  # noqa: E402
from src.utils.llm import LLMClient, ResponseCache  # noqa: E402
from src.utils.schemas import ValidationResult, load_tickets  # noqa: E402
from tests.fake_llm import ScriptedTransport  # noqa: E402

TICKETS = "data/tickets/synthetic_tickets.json"
HAPPY_PATH = "TCK-1143"
SILENT_REFERRAL = "TCK-1078"


@pytest.fixture(scope="module")
def tickets():
    return {t.ticket_id: t for t in load_tickets(resolve(TICKETS))}


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """Every write this phase makes lands in tmp_path, including the audit log."""
    from src.memory.customer_thread_store import CustomerThreadStore
    from src.retrieval.bm25 import BM25Index
    from src.retrieval.retriever import Retriever

    CustomerThreadStore.reset_default()
    monkeypatch.setitem(app_config()["paths"], "outputs", str(tmp_path))
    monkeypatch.setitem(
        app_config()["outputs"], "customer_threads", str(tmp_path / "threads.jsonl")
    )
    node_mod._audit_loggers.clear()
    node_mod.set_retriever(
        Retriever(BM25Index.from_knowledge_base(), k=5, similarity_floor=0.0,
                  routing_rules=routing_rules())
    )
    yield
    CustomerThreadStore.reset_default()
    node_mod.set_retriever(None)
    llm_mod.set_default_client(None)


# ---------------------------------------------------------------------------------- harness


def scripted_transport(tmp_path, **kwargs) -> ScriptedTransport:
    """Install a fake model and hand back the transport, so prompts can be inspected."""
    transport = ScriptedTransport(**kwargs)
    llm_mod.set_default_client(
        LLMClient(cache=ResponseCache(tmp_path / "llm-cache"), transport=transport)
    )
    return transport


def graph_on(database):
    """
    A freshly compiled graph over one sqlite file.

    A new saver -- and so a new connection -- every time on purpose: the restart test needs two
    graphs that share nothing but the file on disk.

    Built through `sqlite_saver`, the same helper the app uses, so a saver that only works in
    the tests is not a way this can pass.
    """
    return build_graph(checkpointer=sqlite_saver(database))


def thread_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}


def suspend(ticket, database, tmp_path, **transport_kwargs):
    """Run one ticket in interactive mode until it stops at `hitl_gate`."""
    transport = scripted_transport(tmp_path, **transport_kwargs)
    run_id = new_run_id()
    thread_id = f"{run_id}:{ticket.ticket_id}"
    graph = graph_on(database)
    state = graph.invoke(
        dict(initial_state(ticket, run_id=run_id, hitl_mode="interactive")),
        config=thread_config(thread_id),
    )
    # Asked of the checkpointer, not of the returned dict: `__interrupt__` on the return value
    # is a convenience that not every langgraph version provides.
    assert interrupt_values(graph.get_state(thread_config(thread_id))), (
        "the graph did not suspend at hitl_gate"
    )
    return graph, thread_id, state, transport


def service_on(graph, tmp_path) -> ReviewService:
    return ReviewService(
        graph=graph,
        queue=ApprovalQueue(tmp_path / "approval_queue.jsonl"),
        reviews_path=tmp_path / "reviews.jsonl",
    )


def reviewed(service: ReviewService, thread_id: str, action: str, **kwargs):
    result = service.submit(thread_id, action, **kwargs)
    return result, service.review_records()[-1]


# ------------------------------------------------------------------------------- THE GATE


def test_a_suspended_review_survives_a_process_restart(tmp_path, tickets):
    """
    The P7 gate: a paused review resumes from the sqlite file alone.

    Prevents the failure where interactive review works only for as long as the Streamlit
    process that started it lives -- with `memory` the queue file would point at threads that
    no longer exist anywhere.
    """
    database = tmp_path / "checkpoints.sqlite"
    ticket = tickets[HAPPY_PATH]
    graph, thread_id, suspended_state, _ = suspend(ticket, database, tmp_path)

    route_before = suspended_state["route"]
    draft_before = suspended_state["draft"]
    retrieved_before = [chunk.policy_id for chunk in suspended_state["retrieved"]]
    assert draft_before, "nothing to review: drafting produced no text before the interrupt"

    # The restart. Nothing from the first process is reachable after this line.
    del graph, suspended_state
    gc.collect()

    resumed = graph_on(database).invoke(
        Command(resume={"action": "APPROVE", "comments": "checked", "reviewer": "srinivas"}),
        config=thread_config(thread_id),
    )

    assert resumed["reviewer"].action == "APPROVE"
    assert resumed["reviewer"].reviewer == "srinivas"
    assert resumed["finished_at"] is not None, "the run did not reach audit_log"
    # Pre-interrupt state intact: the reviewer approved what they were shown.
    assert resumed["route"] == route_before
    assert resumed["draft"] == draft_before
    assert [chunk.policy_id for chunk in resumed["retrieved"]] == retrieved_before


# ------------------------------------------------------------------ the checkpointer itself


def test_the_metadata_column_is_json_the_saver_can_filter_on(tmp_path):
    """
    Why `sqlite_saver` exists rather than a bare `SqliteSaver(sqlite3.connect(...))`.

    langgraph-checkpoint 4.x dropped the untyped `dumps`/`loads` from `JsonPlusSerializer`;
    langgraph-checkpoint-sqlite still calls them on the metadata column, so every `put()` raised
    `AttributeError: 'JsonPlusSerializer' object has no attribute 'dumps'` and no review could
    reach disk. Asserted here and not only through the gate, because eleven AttributeErrors from
    eleven tests do not say which of the two packages is wrong.

    Two assertions, because the format matters as much as the write: the saver's own filter
    compiles to `json_extract(CAST(metadata AS TEXT), '$.key')`, so a non-JSON encoding would
    write, resume, and then silently match nothing on `list`.
    """
    from langgraph.checkpoint.base import empty_checkpoint

    database = tmp_path / "checkpoints.sqlite"
    saver = sqlite_saver(database)
    config = {"configurable": {"thread_id": "run-1:TCK-1143", "checkpoint_ns": ""}}

    saved = saver.put(config, empty_checkpoint(), {"source": "loop", "step": 3}, {})

    assert saver.get_tuple(saved).metadata["source"] == "loop", "the read path lost the metadata"
    stored = sqlite3.connect(str(database)).execute("SELECT metadata FROM checkpoints").fetchone()
    assert json.loads(stored[0])["step"] == 3, "the metadata column is not JSON text"
    assert list(saver.list(config, filter={"source": "loop"})), (
        "list(filter=...) matched nothing: the written and queried encodings disagree"
    )


def test_the_metadata_serializer_is_installed_only_when_the_library_lacks_one():
    """
    The repair is conditional. On a matched pair of packages the library's serializer handles
    more types than `default=str` does and has to stay in charge -- an unconditional repair
    would quietly downgrade a working install, and would have to be remembered and removed the
    day the sqlite saver catches up with core.
    """

    class TypedOnly:  # what core 4.x ships
        def dumps_typed(self, obj):
            return ("json", b"{}")

        def loads_typed(self, data):
            return {}

    class WithUntyped(TypedOnly):  # what the sqlite saver was written against
        def dumps(self, obj):
            return b"library"

        def loads(self, data):
            return {"from": "library"}

    class Saver:
        def __init__(self, serde):
            self.jsonplus_serde = serde

    repaired = repair_metadata_serializer(Saver(TypedOnly())).jsonplus_serde
    assert isinstance(repaired, JsonMetadataSerializer)
    kept = repair_metadata_serializer(Saver(WithUntyped())).jsonplus_serde
    assert kept.dumps({}) == b"library", "a serializer that already worked was replaced"

    # Metadata is the filter index, never the source for a resume, so a value JSON cannot encode
    # must degrade rather than stop a suspended review from being written.
    serializer = JsonMetadataSerializer()
    assert serializer.loads(serializer.dumps({"at": object()}))["at"].startswith("<object")


# --------------------------------------------------------------------------- the six actions


def test_approve_terminates_into_audit(tmp_path, tickets):
    """APPROVE ends the run. Nothing regenerates and the audit record is written."""
    graph, thread_id, _, _ = suspend(tickets[HAPPY_PATH], tmp_path / "cp.sqlite", tmp_path)
    service = service_on(graph, tmp_path)

    result, record = reviewed(service, thread_id, "APPROVE", comments="fine")

    assert result.terminated and not result.regenerated
    assert record["action"] == "APPROVE"
    assert record["edited_draft"] is None
    assert service.pending() == []


def test_approve_and_route_records_the_confirmed_target(tmp_path, tickets):
    """APPROVE_AND_ROUTE keeps the queue the case was sent to, which is the whole point of it."""
    graph, thread_id, state, _ = suspend(
        tickets[SILENT_REFERRAL], tmp_path / "cp.sqlite", tmp_path
    )
    service = service_on(graph, tmp_path)
    target = state["escalation_target"]
    assert target, "this ticket was expected to name an internal queue"

    _, record = reviewed(service, thread_id, "APPROVE_AND_ROUTE")

    assert record["agent_escalation_target"] == target
    assert record["route_override"] is False


def test_an_edited_draft_leaves_the_original_recoverable(tmp_path, tickets):
    """
    EDIT stores both versions.

    Edit size is the quality signal you cannot compute once you have overwritten the thing you
    would measure against, so `state["draft"]` must still hold what the agent wrote.
    """
    graph, thread_id, state, _ = suspend(tickets[HAPPY_PATH], tmp_path / "cp.sqlite", tmp_path)
    service = service_on(graph, tmp_path)
    original = state["draft"]
    rewritten = original + " We have also waived the transfer fee."

    _, record = reviewed(service, thread_id, "EDIT", edited_draft=rewritten)

    assert record["draft"] == original
    assert record["edited_draft"] == rewritten
    assert record["edit_size"] > 0

    final = graph.get_state(thread_config(thread_id)).values
    assert final["draft"] == original, "the original was overwritten in state"
    assert final["reviewer"].edited_draft == rewritten


def test_reject_terminates_and_regenerates_nothing(tmp_path, tickets):
    """REJECT: nothing out, nothing regenerated. A human takes the ticket over."""
    graph, thread_id, _, transport = suspend(
        tickets[HAPPY_PATH], tmp_path / "cp.sqlite", tmp_path
    )
    service = service_on(graph, tmp_path)
    drafts_before = sum(1 for call in transport.calls if call["kind"] == "drafting")

    result, record = reviewed(service, thread_id, "REJECT", comments="not our call to make")

    assert result.terminated and not result.regenerated
    assert record["action"] == "REJECT"
    assert sum(1 for c in transport.calls if c["kind"] == "drafting") == drafts_before


def test_escalate_override_records_both_routes(tmp_path, tickets):
    """
    ESCALATE_OVERRIDE keeps the agent's route standing.

    Rewriting `state["route"]` to the reviewer's answer would quietly move every overridden
    ticket out of the route-accuracy denominator, so the disagreement is recorded instead.
    """
    graph, thread_id, state, _ = suspend(tickets[HAPPY_PATH], tmp_path / "cp.sqlite", tmp_path)
    service = service_on(graph, tmp_path)
    agent_route = state["route"]

    _, record = reviewed(
        service, thread_id, "ESCALATE_OVERRIDE",
        comments="the customer is threatening litigation",
        escalation_target="Executive Complaints",
    )

    assert record["agent_route"] == agent_route
    assert record["reviewer_route"] == "ESCALATE"
    assert record["reviewer_escalation_target"] == "Executive Complaints"
    assert record["route_override"] is True
    assert graph.get_state(thread_config(thread_id)).values["route"] == agent_route


def test_regeneration_re_enters_drafting_with_the_comment(tmp_path, tickets):
    """
    REQUEST_REGENERATION is the only re-entry, and it must change the drafting input.

    A regeneration that re-sends the identical prompt spends a call to get the same draft back;
    the reviewer's comment reaching `draft_reply` is what makes the loop worth having.
    """
    graph, thread_id, _, transport = suspend(
        tickets[HAPPY_PATH], tmp_path / "cp.sqlite", tmp_path
    )
    service = service_on(graph, tmp_path)
    comment = "say explicitly that the fee has already been credited"

    result, _ = reviewed(service, thread_id, "REQUEST_REGENERATION", comments=comment)

    drafting = [call["prompt"] for call in transport.calls if call["kind"] == "drafting"]
    assert len(drafting) == 2, "drafting did not run again"
    assert comment in drafting[-1]
    assert result.regenerated and not result.terminated
    # Back on the queue as a fresh pending review: one audit record, two review records.
    assert [review.entry.ticket_id for review in service.pending()] == [HAPPY_PATH]


def test_regeneration_stops_at_the_cap(tmp_path, tickets):
    """
    The reviewer loop is capped like the other three, and the cap terminates the run.

    Without it a reviewer holding the button creates a fourth cycle that no counter bounds.
    """
    graph, thread_id, _, _ = suspend(tickets[HAPPY_PATH], tmp_path / "cp.sqlite", tmp_path)
    service = service_on(graph, tmp_path)
    cap = service.regeneration_cap()

    for _ in range(cap):
        result = service.submit(thread_id, "REQUEST_REGENERATION", comments="again")
    assert result.terminated, f"the {cap}th regeneration did not stop the loop"

    final = graph.get_state(thread_config(thread_id)).values
    assert final["regeneration_attempts"] == cap
    assert "review_regeneration" in final["loops_capped"]
    assert final["finished_at"] is not None


# --------------------------------------------------------------------------- the other modes


@pytest.mark.parametrize("mode", ["auto", "simulate"])
def test_auto_and_simulate_never_interrupt(mode, tmp_path, tickets, monkeypatch):
    """
    An `interrupt()` on a batch path hangs every eval run waiting for a person who is not there.

    The sentinel makes that failure loud instead of a stalled process.
    """
    import langgraph.types

    def forbidden(_payload):
        raise AssertionError(f"{mode} mode called interrupt()")

    monkeypatch.setattr(langgraph.types, "interrupt", forbidden)
    scripted_transport(tmp_path)

    state = walk_graph(
        dict(initial_state(tickets[HAPPY_PATH], run_id=new_run_id(), hitl_mode=mode))
    )
    assert state["reviewer"] is not None
    assert state["reviewer"].mode == mode


def test_interactive_refuses_a_memory_checkpointer(monkeypatch):
    """
    Failing loudly beats falling back to `auto`.

    A silent fallback lets someone publish an "interactive" edit rate that no human produced,
    which is the failure the three-mode design exists to prevent.
    """
    monkeypatch.setitem(app_config()["graph"], "checkpointer", "memory")
    with pytest.raises(InteractiveReviewUnavailable, match="sqlite"):
        require_durable_checkpointer()


def test_a_misconfigured_install_says_so_before_showing_an_empty_queue(monkeypatch, tmp_path):
    """
    An empty queue and a queue that cannot be read look identical on screen.

    Nothing touches the graph while the queue file is empty, so without this check a `memory`
    install renders "nothing pending" and the reviewer concludes there is nothing to review —
    the quiet version of the fallback `require_durable_checkpointer` refuses to make.
    """
    monkeypatch.setitem(app_config()["graph"], "checkpointer", "memory")
    service = ReviewService(
        queue=ApprovalQueue(tmp_path / "queue.jsonl"), reviews_path=tmp_path / "reviews.jsonl"
    )
    assert service.pending() == []
    assert "sqlite" in (service.configuration_problem() or "")

    monkeypatch.setitem(app_config()["graph"], "checkpointer", "sqlite")
    assert service.configuration_problem() is None


# -------------------------------------------------------------------------- the silent case


def test_a_silent_referral_is_flagged_to_the_reviewer_and_absent_from_the_draft(
    tmp_path, tickets
):
    """
    TCK-1078: refused, referred, and the reply says nothing about it.

    Naming a Conduct Review referral warns exactly the person the account holder may need
    protecting from, so the screen has to make the invisibility unmissable and the validator
    has to catch a draft that breaks it.
    """
    _, _, state, _ = suspend(tickets[SILENT_REFERRAL], tmp_path / "cp.sqlite", tmp_path)

    payload = review_payload(state)
    assert payload["escalation_visible_to_customer"] is False, (
        "the ticket this test exists for did not produce a silent referral"
    )
    assert payload["escalation_target"], "a silent referral with no queue tells the reviewer nothing"
    assert payload["escalation_target"].lower() not in payload["draft"].lower()

    # And a draft that does name it fails validation rather than reaching the queue.
    leaked = dict(state)
    leaked["draft"] = f"We have referred this to {state['escalation_target']}."
    leaked["validation"] = ValidationResult(ok=True)
    assert not node_mod.validate_draft(leaked)["validation"].ok


def test_the_payload_shows_an_empty_bypass_as_correct(tmp_path, tickets):
    """
    A safety-critical ticket reaches review with `retrieved == []` by design.

    The screen has to say so; a blank evidence panel that looks broken teaches the reviewer to
    distrust the one path where an empty context is the safety property.
    """
    _, _, state, _ = suspend(tickets["TCK-1019"], tmp_path / "cp.sqlite", tmp_path)

    payload = review_payload(state)
    assert payload["retrieval_mode"] == "bypassed"
    assert payload["retrieved"] == []
    assert payload["route"] == "ESCALATE"


# ---------------------------------------------------------------------------------- the queue


def test_the_queue_folds_a_ticket_reviewed_twice(tmp_path):
    """
    Pending is a fold over an append-only file, never a rewrite.

    A ticket sent back and then approved writes queued/reviewed/queued/reviewed. Counting
    `queued` lines would leave it pending forever; rewriting the file to delete lines would let
    it drift from the checkpointer, which is the source of truth.
    """
    queue = ApprovalQueue(tmp_path / "queue.jsonl")
    entry = QueueEntry(run_id="r1", ticket_id="TCK-1143", subject="fee")

    queue.append_queued(entry)
    queue.append_reviewed("r1", "TCK-1143", "REQUEST_REGENERATION")
    queue.append_queued(entry)
    assert [e.ticket_id for e in queue.pending()] == ["TCK-1143"]

    queue.append_reviewed("r1", "TCK-1143", "APPROVE")
    assert queue.pending() == []
    # Four lines still on disk: the history is the record, and nothing was rewritten.
    assert len(queue.records()) == 4


def test_the_queue_filters_live_in_the_service_not_the_app():
    """
    Sorting and filtering are decisions, so they are testable rather than inline in a Streamlit
    script that re-executes on every click.
    """
    disagreed = PendingReview(
        entry=QueueEntry(run_id="r", ticket_id="T1", route="ESCALATE", proposals_disagree=True),
        checkpoint_status="suspended",
    )
    agreed = PendingReview(
        entry=QueueEntry(run_id="r", ticket_id="T2", route="REFUSE"),
        checkpoint_status="missing",
    )

    assert [r.entry.ticket_id for r in filter_pending(
        [disagreed, agreed], routes=["ESCALATE", "REFUSE"], disagreed_only=True
    )] == ["T1"]
    assert len(filter_pending(
        [disagreed, agreed], routes=["ESCALATE"], disagreed_only=False
    )) == 1

    resumable, drifted = split_by_agreement([disagreed, agreed])
    assert [r.entry.ticket_id for r in resumable] == ["T1"]
    assert [r.entry.ticket_id for r in drifted] == ["T2"]


def test_a_queue_entry_reconstructs_its_thread_id():
    """A restart resumes from the entry alone; nothing may depend on the previous process."""
    assert QueueEntry(run_id="20260821T171714Z-0a04", ticket_id="TCK-1125").thread_id == (
        "20260821T171714Z-0a04:TCK-1125"
    )


def test_fold_ignores_unknown_keys_from_an_older_file():
    """The queue is append-only and outlives any one shape of QueueEntry."""
    pending = fold_pending(
        [{"event": "queued", "run_id": "r1", "ticket_id": "T1", "retired_field": 3}]
    )
    assert [entry.ticket_id for entry in pending] == ["T1"]


# --------------------------------------------------------------------------------- measuring


def test_edit_size_is_a_proportion_of_the_original():
    assert edit_size("hello", "hello") == 0.0
    assert edit_size("hello", "hello world") == pytest.approx(6 / 5, rel=1e-3)
    assert edit_size("", "anything") == 1.0


def test_metrics_are_split_by_mode_and_carry_their_denominator():
    """
    Pooling modes produces a number that describes neither, and a rate without its denominator
    cannot be distinguished from a rate over nothing -- the failure that let three evaluator
    tests here pass on an empty set.
    """
    records = [
        {"mode": "interactive", "action": "EDIT", "draft": "abcd", "edited_draft": "abcdef",
         "agent_route": "AUTO_RESOLVE", "proposals_disagree": True},
        {"mode": "interactive", "action": "ESCALATE_OVERRIDE", "agent_route": "AUTO_RESOLVE",
         "proposals_disagree": False},
        {"mode": "auto", "action": "APPROVE", "agent_route": "ESCALATE"},
    ]
    metrics = review_metrics(records)

    assert set(metrics) == {"interactive", "auto"}
    assert metrics["interactive"]["n"] == 2
    assert metrics["interactive"]["edit_rate"] == 0.5
    assert metrics["interactive"]["override_rate"] == 0.5
    assert metrics["interactive"]["edits_measured"] == 1
    assert metrics["interactive"]["disagreement_rate"] == 0.5
    assert metrics["auto"]["n"] == 1
    assert metrics["auto"]["edit_rate"] == 0.0


def test_metrics_over_nothing_report_nothing():
    """An empty reviews file must produce no modes at all, not a row of confident zeros."""
    assert review_metrics([]) == {}


def test_review_records_are_written_one_line_per_decision(tmp_path, tickets):
    """
    Separate from the audit log because the audit log is per run and this is per decision: a
    ticket regenerated once and then approved has one audit record and two review records.
    """
    graph, thread_id, _, _ = suspend(tickets[HAPPY_PATH], tmp_path / "cp.sqlite", tmp_path)
    service = service_on(graph, tmp_path)

    service.submit(thread_id, "REQUEST_REGENERATION", comments="again please")
    service.submit(thread_id, "APPROVE")

    lines = (tmp_path / "reviews.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["action"] for line in lines] == [
        "REQUEST_REGENERATION",
        "APPROVE",
    ]
    audits = list((tmp_path / "audit_logs").glob("run_*.jsonl"))
    assert len(audits) == 1
    assert len(audits[0].read_text(encoding="utf-8").strip().splitlines()) == 1
