"""
The adapter between the review surface and the graph: what is pending, what the reviewer sees,
what happens when they act, and what all of it measured.

`app/streamlit_app.py` renders and decides nothing. Two reasons, and the second is the one that
bites: Streamlit re-executes its whole script on every widget interaction, so anything with a
side effect in the app file runs an unpredictable number of times; and a Streamlit script is
awkward to test, while this module is ordinary Python.

This is the real adapter, not the `approval_ui_stub` the early LLD notes parked here -- calling
it a stub would tell the next reader the wrong thing about where the logic lives.
"""

from __future__ import annotations

import difflib
import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.hitl.approval_queue import ApprovalQueue, QueueEntry
from src.hitl.reviewer_actions import ACTIONS, spec
from src.utils.config import app_config, resolve

log = logging.getLogger(__name__)

REGENERATION_LOOP = "review_regeneration"


class InteractiveReviewUnavailable(RuntimeError):
    """
    Raised instead of quietly running in `auto`.

    A fallback here would let someone publish an "interactive" edit rate that no human ever
    produced, which is the one failure mode the three-mode design exists to prevent.
    """


# ------------------------------------------------------------------------------- checkpointer


def checkpointer_kind() -> str:
    return str(app_config().get("graph", {}).get("checkpointer", "memory")).lower()


def require_durable_checkpointer() -> None:
    """
    Interactive review needs `sqlite`. `memory` dies with the process, which for a suspended
    review means the ticket is unresumable and the queue file points at nothing.

    Left as an explicit check rather than silently forcing sqlite, so `config/app_config.yaml`
    never disagrees with what actually ran.
    """
    if checkpointer_kind() != "sqlite":
        raise InteractiveReviewUnavailable(
            f"graph.checkpointer is {checkpointer_kind()!r}; interactive review needs 'sqlite'. "
            "Set graph.checkpointer: sqlite in config/app_config.yaml -- with 'memory' a "
            "suspended review does not survive the process that created it."
        )


# ---------------------------------------------------------------------------- pending reviews


@dataclass(frozen=True)
class PendingReview:
    """A queue entry plus what the checkpointer says about the same thread."""

    entry: QueueEntry
    checkpoint_status: str  # suspended | not_suspended | missing

    @property
    def thread_id(self) -> str:
        return self.entry.thread_id

    @property
    def agrees(self) -> bool:
        return self.checkpoint_status == "suspended"


def interrupt_values(snapshot: Any) -> list[Any]:
    """
    The payloads of every interrupt waiting on a snapshot.

    Read from `.interrupts` when the installed langgraph exposes it and from `.tasks` otherwise;
    the attribute moved between versions and the pending screen must not depend on which one is
    installed.
    """
    direct = getattr(snapshot, "interrupts", None)
    if direct:
        return [getattr(item, "value", item) for item in direct]
    return [
        getattr(item, "value", item)
        for task in getattr(snapshot, "tasks", ()) or ()
        for item in getattr(task, "interrupts", ()) or ()
    ]


# ------------------------------------------------------------------------------- edit metrics


def edit_size(original: str, edited: str) -> float:
    """
    Changed characters as a proportion of the original. 0.0 means untouched.

    Deliberately uncapped: a reviewer who wrote three times as much scores above 1.0, and
    clamping that to "completely rewritten" would hide the difference between a rewrite and a
    rewrite that also had to explain itself.
    """
    if not original:
        return 1.0 if edited else 0.0
    matcher = difflib.SequenceMatcher(None, original, edited, autojunk=False)
    changed = sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    )
    return round(changed / len(original), 4)


def review_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Edit rate and override rate, per HITL mode. HLD §7.5's two production quality signals.

    Modes are never pooled. An `auto`-mode approval is not evidence about what a human would
    have done, and averaging the two produces a number that describes neither.

    Every figure ships with its denominator. Three evaluator tests in this repo passed on an
    empty set before that was caught, and a 0.0 edit rate over zero decisions looks identical
    to a perfect one.
    """
    by_mode: dict[str, dict[str, Any]] = {}
    for record in records:
        mode = str(record.get("mode") or "unknown")
        by_mode.setdefault(mode, {"decisions": []})["decisions"].append(record)

    out: dict[str, dict[str, Any]] = {}
    for mode, bucket in sorted(by_mode.items()):
        decisions = bucket["decisions"]
        total = len(decisions)
        actions = [str(d.get("action")) for d in decisions]
        edits = [
            edit_size(d.get("draft") or "", d.get("edited_draft") or "")
            for d in decisions
            if d.get("action") == "EDIT" and d.get("edited_draft")
        ]
        # Read off the action table rather than testing for ESCALATE_OVERRIDE by name, so a
        # future action that also overrides a route is counted without editing this line.
        overrides = sum(1 for a in actions if a in ACTIONS and ACTIONS[a].counts_as_route_override)

        out[mode] = {
            "n": total,
            "edit_rate": round(sum(1 for a in actions if a == "EDIT") / total, 4) if total else 0.0,
            "override_rate": round(overrides / total, 4) if total else 0.0,
            "median_edit_size": round(statistics.median(edits), 4) if edits else 0.0,
            "edits_measured": len(edits),
            "regeneration_rate": (
                round(sum(1 for a in actions if a == "REQUEST_REGENERATION") / total, 4)
                if total
                else 0.0
            ),
            "reject_rate": round(sum(1 for a in actions if a == "REJECT") / total, 4)
            if total
            else 0.0,
            "action_counts": {action: actions.count(action) for action in sorted(set(actions))},
            "route_distribution": _counts(d.get("agent_route") for d in decisions),
            "disagreement_rate": (
                round(sum(1 for d in decisions if d.get("proposals_disagree")) / total, 4)
                if total
                else 0.0
            ),
        }
    return out


def _counts(values: Any) -> dict[str, int]:
    counted: dict[str, int] = {}
    for value in values:
        key = str(value)
        counted[key] = counted.get(key, 0) + 1
    return dict(sorted(counted.items()))


# ------------------------------------------------------------------------------- the service


@dataclass
class SubmitResult:
    """What one submitted decision did to the run."""

    action: str
    terminated: bool
    regenerated: bool
    record: dict[str, Any] = field(default_factory=dict)


class ReviewService:
    """
    One reviewer, one process. Concurrency is out of scope (HLD §11): two processes resuming
    one thread is undefined, and nothing here tries to make it defined.
    """

    def __init__(
        self,
        *,
        graph: Any | None = None,
        queue: ApprovalQueue | None = None,
        reviews_path: Path | str | None = None,
    ) -> None:
        self._graph = graph
        self.queue = queue or ApprovalQueue()
        self.reviews_path = (
            Path(reviews_path) if reviews_path else resolve(app_config()["outputs"]["reviews"])
        )

    # -- graph access ---------------------------------------------------------------------

    @property
    def graph(self) -> Any:
        """
        Compiled once and reused. The checkpointer connection lives inside it, so rebuilding
        per interaction would open a new sqlite handle on every button click.
        """
        if self._graph is None:
            require_durable_checkpointer()
            from src.graph.support_graph import build_graph

            self._graph = build_graph()
        return self._graph

    def configuration_problem(self) -> str | None:
        """
        Why interactive review cannot work right now, or None.

        Separate from `require_durable_checkpointer`, which raises when something tries to use
        the graph. Nothing *touches* the graph while the queue file is empty, so without this a
        misconfigured install renders an empty queue and a reviewer concludes there is nothing
        to review — the quiet version of the fallback this design refuses to make.
        """
        if self._graph is not None:
            return None  # an injected graph brings its own checkpointer; the config is moot
        try:
            require_durable_checkpointer()
        except InteractiveReviewUnavailable as exc:
            return str(exc)
        return None

    def thread_config(self, thread_id: str) -> dict[str, Any]:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": int(app_config().get("graph", {}).get("recursion_limit", 40)),
        }

    def regeneration_cap(self) -> int:
        return int(
            (app_config().get("graph", {}).get("loop_caps", {}) or {}).get(REGENERATION_LOOP, 3)
        )

    def regeneration_allowed(self, payload: dict[str, Any]) -> bool:
        """The UI disables the button here rather than letting a click fail at the cap."""
        return int(payload.get("regeneration_attempts") or 0) < self.regeneration_cap()

    # -- starting a review ------------------------------------------------------------------

    def start_ticket(self, ticket: Any, *, run_id: str, golden: Any = None) -> dict[str, Any]:
        """Build the entry state for one ticket in interactive mode and run it into the queue."""
        from src.graph.graph_state import initial_state

        state = initial_state(ticket, run_id=run_id, golden=golden, hitl_mode="interactive")
        return self.start(dict(state))

    def start(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Run one ticket until it suspends at `hitl_gate`, and index it.

        Returns the state the graph handed back. A ticket that ran to completion instead is not
        an error here -- that is what `auto` and `simulate` do.
        """
        from src.utils.tracing import start_tracing

        # Streamlit is its own process, so the CLI's registration does not cover a run queued
        # from the sidebar. Idempotent, and a no-op while observability.enabled is false.
        start_tracing(state["run_id"])

        thread_id = f"{state['run_id']}:{state['ticket_id']}"
        result = self.graph.invoke(state, config=self.thread_config(thread_id))
        payload = self.suspended_payload(thread_id, result)
        if payload is not None:
            self.queue.append_queued(QueueEntry.from_payload(payload))
        return result

    def suspended_payload(
        self, thread_id: str, result: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """
        The interrupt payload this thread is waiting on, or None if it finished.

        Checks the `invoke` return first and the checkpointer second: `__interrupt__` on the
        returned state is the convenient path but it is not present in every langgraph version,
        and a missed suspension silently leaves a ticket out of the queue.
        """
        interrupts = (result or {}).get("__interrupt__") if isinstance(result, dict) else None
        values = [getattr(item, "value", item) for item in interrupts or ()]
        if not values:
            values = interrupt_values(self.graph.get_state(self.thread_config(thread_id)))
        first = values[0] if values else None
        return first if isinstance(first, dict) else None

    # -- reading the queue ------------------------------------------------------------------

    def pending(self) -> list[PendingReview]:
        """
        The queue, folded, with each entry checked against the checkpointer.

        Least confident first: the decisions the agent was least sure of are the ones most
        worth a human's time.
        """
        reviews = [
            PendingReview(entry=entry, checkpoint_status=self.checkpoint_status(entry.thread_id))
            for entry in self.queue.pending()
        ]
        return sorted(reviews, key=lambda review: review.entry.confidence)

    def checkpoint_status(self, thread_id: str) -> str:
        try:
            snapshot = self.graph.get_state(self.thread_config(thread_id))
        except Exception as exc:  # a corrupt or absent checkpoint is a finding, not a crash
            log.warning("no checkpoint for %s: %s", thread_id, exc)
            return "missing"
        if not getattr(snapshot, "created_at", None) and not getattr(snapshot, "next", None):
            return "missing"
        return "suspended" if interrupt_values(snapshot) else "not_suspended"

    def payload(self, thread_id: str) -> dict[str, Any]:
        """
        What the reviewer sees, read back out of the checkpoint.

        Read from the checkpointer rather than cached in the queue file so that what is on
        screen is what the suspended graph actually holds -- if the two ever diverge, the
        reviewer should be judging the graph.
        """
        snapshot = self.graph.get_state(self.thread_config(thread_id))
        values = interrupt_values(snapshot)
        if not values:
            raise InteractiveReviewUnavailable(
                f"thread {thread_id} is not suspended at a review; the queue file and the "
                "checkpointer disagree, and the checkpointer is the one that is right"
            )
        return values[0]

    # -- recording a decision ---------------------------------------------------------------

    def submit(
        self,
        thread_id: str,
        action: str,
        *,
        comments: str = "",
        edited_draft: str | None = None,
        escalation_target: str | None = None,
        reviewer: str = "reviewer",
    ) -> SubmitResult:
        """
        Resume the graph with one decision, then record it.

        Order matters: the graph runs first, so a decision is only ever recorded as having
        happened if it actually reached the audit log. The reverse leaves `reviews.jsonl`
        claiming a review that the run never saw.
        """
        spec(action)  # raises on an unknown action rather than resuming with a typo
        before = self.payload(thread_id)

        from langgraph.types import Command

        resumed = self.graph.invoke(
            Command(
                resume={
                    "action": action,
                    "comments": comments,
                    "edited_draft": edited_draft,
                    "escalation_target": escalation_target,
                    "reviewer": reviewer,
                }
            ),
            config=self.thread_config(thread_id),
        )

        record = self._write_review_record(
            before,
            action=action,
            comments=comments,
            edited_draft=edited_draft,
            escalation_target=escalation_target,
            reviewer=reviewer,
        )
        self.queue.append_reviewed(before.get("run_id", ""), before.get("ticket_id", ""), action)

        # A regeneration comes straight back to this gate with a new draft, so it is re-queued
        # as a fresh pending review. Two review records, one audit record.
        again = self.suspended_payload(thread_id, resumed)
        if again is not None:
            self.queue.append_queued(QueueEntry.from_payload(again))

        return SubmitResult(
            action=action,
            terminated=again is None,
            regenerated=again is not None,
            record=record,
        )

    def _write_review_record(
        self,
        payload: dict[str, Any],
        *,
        action: str,
        comments: str,
        edited_draft: str | None,
        escalation_target: str | None,
        reviewer: str,
    ) -> dict[str, Any]:
        """
        Append to `outputs/reviews.jsonl`, one line per decision.

        Separate from the audit log because the audit log is per run and this is per decision:
        a ticket sent back for regeneration and then approved has one audit record and two
        review records.
        """
        original = payload.get("draft") or ""
        record = {
            "run_id": payload.get("run_id"),
            "ticket_id": payload.get("ticket_id"),
            "action": action,
            "comments": comments,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "reviewer": reviewer,
            "mode": payload.get("hitl_mode") or "interactive",
            "draft": original,
            "edited_draft": edited_draft,
            "edit_size": edit_size(original, edited_draft) if edited_draft else None,
            # Both routes, always. Override rate is only computable if the agent's answer
            # survives next to the reviewer's.
            "agent_route": payload.get("route"),
            "agent_escalation_target": payload.get("escalation_target"),
            "reviewer_route": "ESCALATE" if action == "ESCALATE_OVERRIDE" else None,
            "reviewer_escalation_target": escalation_target,
            "route_override": spec(action).counts_as_route_override,
            "rule_route": payload.get("rule_route"),
            "llm_route": payload.get("llm_route"),
            "proposals_disagree": bool(payload.get("proposals_disagree")),
            "confidence": payload.get("confidence"),
        }
        self.reviews_path.parent.mkdir(parents=True, exist_ok=True)
        with self.reviews_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return record

    # -- measuring --------------------------------------------------------------------------

    def review_records(self) -> list[dict[str, Any]]:
        if not self.reviews_path.is_file():
            return []
        return [
            json.loads(line)
            for line in self.reviews_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def metrics(self) -> dict[str, Any]:
        """
        The review-side numbers only.

        Everything the golden set scores -- groundedness, citations, confidence calibration --
        belongs to `src/evaluation/` and is read from there, never recomputed here.
        """
        return review_metrics(self.review_records())

    @staticmethod
    def evaluation_report(run_id: str | None = None) -> dict[str, Any] | None:
        """`src.evaluation.report.build` over one run's audit records, or None if there is none."""
        from src.evaluation.report import build
        from src.logging.replay import load_run

        try:
            records = load_run(run_id, latest=run_id is None)
        except FileNotFoundError:
            return None
        return build(records) if records else None


def sample_tickets(count: int) -> list[Any]:
    """The dev batch, so the review surface has something to show without a full run."""
    from src.utils.schemas import load_tickets

    return load_tickets(resolve("data/tickets/sample_ticket_batch.json"))[:count]


def filter_pending(
    reviews: list[PendingReview], *, routes: list[str], disagreed_only: bool
) -> list[PendingReview]:
    """The queue screen's two filters. Here rather than in the app so they can be tested."""
    return [
        review
        for review in reviews
        if review.entry.route in routes
        and (review.entry.proposals_disagree or not disagreed_only)
    ]


def split_by_agreement(
    reviews: list[PendingReview],
) -> tuple[list[PendingReview], list[PendingReview]]:
    """`(resumable, drifted)`. Only the first can be opened; the second has to be shown anyway."""
    return (
        [review for review in reviews if review.agrees],
        [review for review in reviews if not review.agrees],
    )


def confidence_calibration(report: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Pull `confidence_eval`'s calibration table out of a report, non-empty bands only.

    Extraction, not computation: `src/evaluation/` produced every number in here.
    """
    table = next(
        (
            entry["detail"].get("calibration_by_decile")
            for entry in report.get("evaluators", [])
            if entry["name"] == "confidence in-band"
        ),
        None,
    )
    return [{"band": band, **stats} for band, stats in (table or {}).items() if stats["n"]]


def evaluator_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The evaluator table, flattened for display."""
    return [
        {
            "evaluator": entry["name"],
            "score": entry["score"],
            "n": entry["n"],
            "unscored": entry["unscored"],
            "gate": entry["gate"],
        }
        for entry in report.get("evaluators", [])
    ]


def pending_summary_rows(reviews: list[PendingReview]) -> list[dict[str, Any]]:
    """The queue screen's table, flattened. Shaped here so the app file only renders it."""
    return [
        {
            "ticket_id": review.entry.ticket_id,
            "subject": review.entry.subject,
            "route": review.entry.route,
            "confidence": round(review.entry.confidence, 3),
            "escalation_target": review.entry.escalation_target or "—",
            "disagreed": review.entry.proposals_disagree,
            "loop capped": ", ".join(review.entry.loops_capped) or "—",
            "silent referral": not review.entry.escalation_visible_to_customer,
            "checkpoint": review.checkpoint_status,
            "thread_id": review.thread_id,
        }
        for review in reviews
    ]


def action_choices(payload: dict[str, Any], *, regeneration_allowed: bool) -> list[str]:
    """
    The actions offered for this ticket, in the order they should appear.

    `APPROVE_AND_ROUTE` leads when a target exists, because confirming the queue is the common
    case for every ESCALATE and for the REFUSE tickets that still open a file.
    """
    ordered = list(ACTIONS)
    if payload.get("escalation_target"):
        ordered.remove("APPROVE_AND_ROUTE")
        ordered.insert(0, "APPROVE_AND_ROUTE")
    if not regeneration_allowed:
        ordered.remove("REQUEST_REGENERATION")
    return ordered
