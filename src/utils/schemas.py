"""
Every typed object the graph passes around.

Two families, validated to different standards:

- **Input models** (`Ticket` and below) describe data we did not author. `extra="forbid"`, so a
  renamed field fails loudly instead of reading as absent.
- **Working models** describe what nodes produce. Strict about vocabulary, permissive about
  completeness -- a node that has not run has legitimately produced nothing.

`src/retrieval/` uses plain dataclasses, and that is not inconsistency: validate at trust
boundaries, not everywhere.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.utils.constants import (
    Category,
    Difficulty,
    Priority,
    ReviewerAction,
    Route,
    SafetyCode,
    Sentiment,
    Severity,
)


class Strict(BaseModel):
    """Base for data we did not author. An unexpected field is an error, not a shrug."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Working(BaseModel):
    """Base for data nodes produce. Validated on assignment, not frozen."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# ============================================================================= ticket input


class CustomerIdentity(Strict):
    name: str
    email_masked: str
    phone_masked: str


class CustomerContext(Strict):
    """
    The structured record. `prior_fee_reversals_12m` alone decides FEE-001 (courtesy reversal)
    vs FEE-002 (repeat request), and the customer's message reads identically either way.

    The one input model with `extra="allow"`: `account_age_days` is on 1 of 150 tickets, and a
    CRM export legitimately carries per-ticket extras.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    segment: str
    state: str
    tenure_months: int
    relationship_products: list[str] = Field(default_factory=list)
    masked_account: str
    kyc_verified: bool
    prior_tickets_90d: int
    prior_fee_reversals_12m: int
    prior_disputes_12m: int
    account_age_days: int | None = None


class ConversationTurn(Strict):
    """
    Three roles, not two. 6 turns across 4 tickets are `system` -- internal events like
    "Denial letter mailed" (TCK-1044) or "Source IP geolocation: inconsistent" (TCK-1101).
    They are facts to reason from and text that must never be quoted back.
    """

    turn: int
    role: Literal["customer", "agent", "system"]
    timestamp: datetime
    text: str

    @property
    def is_internal(self) -> bool:
        return self.role == "system"


class RelatedTicket(Strict):
    """Seed for case history: how ticket 3 learns that tickets 1 and 2 happened."""

    ticket_id: str
    subject: str
    created_at: datetime
    disposition: str


class Attachment(Strict):
    file_name: str
    content_type: str
    size_kb: int
    scanned: bool


class SLA(Strict):
    first_response_due_at: datetime
    resolution_due_at: datetime


class Ticket(Strict):
    """One CRM record. 150 of these must parse for P0's gate to be green."""

    ticket_id: str
    customer_id: str
    subject: str
    message: str
    conversation_history: list[ConversationTurn] = Field(default_factory=list)
    priority: Priority
    created_at: datetime
    channel: str
    language: str
    locale: str
    category: Category
    product_area: str
    queue: str
    status: str
    tags: list[str] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)
    customer: CustomerIdentity
    customer_context: CustomerContext
    related_tickets: list[RelatedTicket] = Field(default_factory=list)
    sla: SLA
    source_system: str

    @field_validator("created_at")
    @classmethod
    def _reject_naive_timestamps(cls, value: datetime) -> datetime:
        # Sorting a mix of aware and naive datetimes raises TypeError three modules away.
        if value.tzinfo is None:
            raise ValueError("created_at must carry a UTC offset")
        return value

    @property
    def is_repeat_contact(self) -> bool:
        return bool(self.conversation_history) or bool(self.related_tickets)

    @property
    def system_events(self) -> list[ConversationTurn]:
        """Internal turns only. A prompt has to ask for these explicitly."""
        return [turn for turn in self.conversation_history if turn.is_internal]

    def transcript(self, *, include_internal: bool = True) -> str:
        """Full thread, oldest first. Drafting prompts should pass `include_internal=False`."""
        lines = [
            f"[{turn.role} @ {turn.timestamp.isoformat()}] {turn.text}"
            for turn in self.conversation_history
            if include_internal or not turn.is_internal
        ]
        lines.append(f"[customer @ {self.created_at.isoformat()}] {self.message}")
        return "\n".join(lines)


# ============================================================================ golden labels


class GroundingClaim(Strict):
    """`policy_id` is nullable: some claims are about the action, not about a clause."""

    policy_id: str | None = None
    claim: str


class GoldenRecord(Strict):
    """One full evaluation label. Covers 107 of the 150 tickets."""

    ticket_id: str
    subject: str
    category: Category
    difficulty: Difficulty
    expected_route: Route
    expected_escalation_target: str | None = None
    expected_sentiment: Sentiment
    expected_kb_sources: list[str] = Field(default_factory=list)
    expected_policy_ids: list[str] = Field(default_factory=list)
    no_policy_in_kb: bool = False
    expected_confidence_band: tuple[float, float]
    grounding_claims_required: list[GroundingClaim] = Field(default_factory=list)
    must_not_contain: list[str] = Field(default_factory=list)
    expected_reviewer_action: ReviewerAction
    priority: Priority
    label_rationale: str = ""

    @property
    def is_hard(self) -> bool:
        return self.difficulty == "hard"


class RouteLabel(Strict):
    """The lighter label, present for all 150. Route accuracy is scored against this."""

    route: Route
    category: Category
    difficulty: Difficulty
    escalation_target: str | None = None
    no_policy_in_kb: bool = False


# =========================================================================== working models


class SafetyFlag(Working):
    """`evidence_span` makes a P2 false positive reviewable by eye."""

    code: SafetyCode
    clause_id: str | None = None
    evidence_span: str = ""
    severity: Severity = "medium"
    detector: Literal["pattern", "model"] = "pattern"

    @property
    def is_critical(self) -> bool:
        from src.utils.constants import SAFETY_CRITICAL_CODES

        return self.code in SAFETY_CRITICAL_CODES


class Precondition(Working):
    """
    One deterministic policy test.

    `met` is a tri-state. `None` means "not determinable from the record" and drives
    ASK_MORE_INFO; `False` drives a different route. Collapsing them turns "we don't know"
    into "no", which is a confident wrong answer.

    `inputs` stores what the verdict was computed from, so the record is replayable.
    """

    name: str
    met: bool | None
    reason: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)

    @property
    def indeterminate(self) -> bool:
        return self.met is None


class ClauseRef(Working):
    policy_id: str
    why: str = ""


class ClauseConstraint(Working):
    policy_id: str
    constraint: str


class ClauseConflict(Working):
    between: list[str]
    resolution: str


class PolicyAnalysis(Working):
    """
    What `analyse_policy` hands `route_decision`.

    Deciding vs constraining is the split that makes conflicting-guidance tickets tractable:
    DSP-003 decides (re-opened claim -> escalate), DSP-006 only constrains (do not explain how
    'verified' was determined). Merged into one list, a gag rule reads as a reason to escalate.
    """

    deciding_clauses: list[ClauseRef] = Field(default_factory=list)
    constraining_clauses: list[ClauseConstraint] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    policy_verified: bool = False
    conflicts: list[ClauseConflict] = Field(default_factory=list)
    self_certainty: float = 0.0

    def deciding_ids(self) -> list[str]:
        return [clause.policy_id for clause in self.deciding_clauses]


class RetrievedChunk(Working):
    """A retrieval hit, flattened for state and for the audit record."""

    chunk_id: str
    policy_id: str = ""
    source_file: str = ""
    chunk_type: str = ""
    title: str = ""
    text: str = ""
    similarity: float | None = None
    citable: bool = True
    injected: bool = False


class RetrievalAttempt(Working):
    """One pass of the retrieval loop, recorded per attempt rather than overwritten."""

    attempt: int
    query: str
    mode: str = "dense"
    top_similarity: float = 0.0
    policy_ids: list[str] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)
    below_floor: bool = False
    scope_signal: bool = False


class ValidationResult(Working):
    """
    Two failure lists, because they are different mistakes. A hallucinated citation means the
    model invented a policy; an uncitable one means the content is real and the audience wrong.
    """

    ok: bool = True
    violations: list[str] = Field(default_factory=list)
    hallucinated_citations: list[str] = Field(default_factory=list)
    uncitable_citations: list[str] = Field(default_factory=list)

    @property
    def is_hard_failure(self) -> bool:
        return bool(self.hallucinated_citations)


class ReviewerDecision(Working):
    """`edited_draft` sits alongside the original: edit size is a quality signal."""

    action: ReviewerAction
    comments: str = ""
    edited_draft: str | None = None
    reviewed_at: datetime | None = None
    reviewer: str = "unknown"
    mode: str = "auto"


class NodeTrace(Working):
    """One node execution: what ran and how long it took."""

    node: str
    started_at: datetime
    ms: float = 0.0
    summary: str = ""


class CaseSummary(Working):
    """
    What one earlier ticket contributes to the next from the same customer.

    Carries a disposition (what happened) rather than the previous decision object, so the
    agent cannot compound its own earlier mistake across a thread.
    """

    ticket_id: str
    subject: str
    created_at: datetime
    disposition: str
    route: Route | None = None
    escalation_target: str | None = None


# ============================================================================ serialisation


def jsonable(value: Any) -> Any:
    """
    Recursively turn models, datetimes and containers into JSON-safe values.

    `mode="json"` is the part people miss -- plain `model_dump()` leaves datetimes in place, and
    they only fail at `json.dumps` time, three modules away from the node that produced them.

    Lives here rather than in `logging/audit_logger.py` because `graph_state.review_payload`
    needs it too, and `graph_state` cannot import the audit logger without a cycle.
    """
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


# ================================================================================== loaders


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(f"data file missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _records(payload: Any, key: str) -> list[dict[str, Any]]:
    """Unwrap the `{"dataset": ..., "<key>": [...]}` envelope, or accept a bare list."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and key in payload:
        return payload[key]
    raise ValueError(f"expected a list or a dict with a {key!r} key")


def load_tickets_from_records(records: list[dict[str, Any]]) -> list[Ticket]:
    """
    Parse and sort by arrival time.

    The sort is the invariant behind case history: a ticket must never be scored before its own
    predecessor is recorded. Enforcing it here means nobody else has to remember it. Split out
    from `load_tickets` so a test can feed it deliberately shuffled input.
    """
    tickets = [Ticket.model_validate(record) for record in records]
    return sorted(tickets, key=lambda ticket: (ticket.created_at, ticket.ticket_id))


def load_tickets(path: Path | str) -> list[Ticket]:
    return load_tickets_from_records(_records(_read_json(Path(path)), "tickets"))


def load_golden(path: Path | str) -> dict[str, GoldenRecord]:
    """Keyed by ticket_id -- every caller wants a lookup."""
    records = _records(_read_json(Path(path)), "records")
    return {r["ticket_id"]: GoldenRecord.model_validate(r) for r in records}


def load_expected_routes(path: Path | str) -> dict[str, RouteLabel]:
    """
    All 150 route labels. Note the envelope differs: `labels` is a mapping, not a list.

    Route accuracy is scored on this file; groundedness and citations can only be scored on the
    107 in `golden_dataset.json`.
    """
    payload = _read_json(Path(path))
    labels = payload["labels"] if isinstance(payload, dict) else payload
    return {ticket_id: RouteLabel.model_validate(row) for ticket_id, row in labels.items()}
