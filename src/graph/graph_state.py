"""
The state the graph threads through twelve nodes, plus the helpers routers read.

A TypedDict rather than a Pydantic model because nodes return **partial** dicts and LangGraph
merges them. The values in state are still Pydantic models, so only the envelope is loose.

Four keys use an `operator.add` reducer and concatenate instead of overwriting. For those,
a node returns **the delta**, not the new whole:

    return {"trace": state["trace"] + [t]}   # wrong -- duplicates everything so far
    return {"trace": [t]}                    # right

Nothing is mutated in place. A checkpointer snapshots state between nodes, and mutating a list
an earlier snapshot points at makes the replay lie.
"""

from __future__ import annotations

import operator
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict

from src.utils.constants import LOOP_COUNTERS, Route, Sentiment
from src.utils.schemas import (
    CaseSummary,
    GoldenRecord,
    NodeTrace,
    PolicyAnalysis,
    Precondition,
    RetrievalAttempt,
    RetrievedChunk,
    ReviewerDecision,
    SafetyFlag,
    Ticket,
    ValidationResult,
    jsonable,
)


class GraphState(TypedDict, total=False):
    """
    `total=False`: at START only the entry keys exist. Pre-filling everything with `None` would
    make "not computed yet" and "computed as nothing" indistinguishable, and those need
    different routes.
    """

    # entry
    run_id: str
    ticket_id: str
    ticket: Ticket
    golden: GoldenRecord | None  # None for the 43 tickets outside the golden set
    customer_history: list[CaseSummary]

    # triage
    sentiment: Sentiment
    safety_flags: list[SafetyFlag]
    safety_critical: bool  # derived, but stored: it is the branch condition
    intent: str
    entities: dict[str, Any]

    # rule engine
    preconditions: dict[str, Precondition]

    # retrieval
    retrieval_query: str
    retrieval_mode: str  # dense | bypassed | stubbed -- recorded, never inferred
    retrieved: list[RetrievedChunk]
    context_block: str  # what the model actually saw, verbatim
    retrieval_attempts: int
    k_override: int | None
    retrieval_log: Annotated[list[RetrievalAttempt], operator.add]

    # reasoning
    policy_analysis: PolicyAnalysis

    # routing -- the two proposals are kept apart because the gap between them is the signal
    rule_route: Route | None
    llm_route: Route | None
    route: Route
    escalation_target: str | None  # valid on REFUSE too
    escalation_visible_to_customer: bool  # False for abuse referrals
    route_rationale: str

    # confidence
    confidence: float
    confidence_parts: dict[str, float]
    recheck_attempts: int

    # drafting
    draft: str
    cited_policy_ids: list[str]
    validation: ValidationResult
    draft_attempts: int

    # review
    reviewer: ReviewerDecision | None
    hitl_mode: str
    regeneration_attempts: int  # cap: a reviewer cannot cycle a draft forever

    # cross-cutting
    trace: Annotated[list[NodeTrace], operator.add]
    loops_capped: Annotated[list[str], operator.add]
    notes: Annotated[list[str], operator.add]
    stubs: dict[str, Any]  # test scripting; see nodes.scripted_value
    no_model: bool  # run the deterministic layers only -- no API key needed
    finished_at: datetime | None


def new_run_id() -> str:
    """Sortable and unique: `20260820T161500Z-4f2a`. Audit logs are one file per run."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:4]}"


def initial_state(
    ticket: Ticket,
    *,
    run_id: str,
    golden: GoldenRecord | None = None,
    customer_history: list[CaseSummary] | None = None,
    hitl_mode: str = "auto",
    stubs: dict[str, Any] | None = None,
    no_model: bool = False,
) -> GraphState:
    """
    The state a run starts from.

    Loop counters are initialised to 0 rather than left absent -- routers read them on every
    pass, and a `.get(key, 0)` in five places is five chances to typo the default.

    `customer_history=None` means "load it from the thread store". Passing `[]` opts out
    explicitly. The default loads, because the alternative -- every caller remembering -- is
    how case history came to be inert: it was wired into `main.py` and silently absent from
    `route_eval`, so the four escalating threads got no benefit from it in any measurement.
    """
    if customer_history is None:
        from src.memory.customer_thread_store import CustomerThreadStore

        customer_history = CustomerThreadStore.default().history_for(ticket)

    return GraphState(
        run_id=run_id,
        ticket_id=ticket.ticket_id,
        ticket=ticket,
        golden=golden,
        customer_history=customer_history,
        retrieval_attempts=0,
        recheck_attempts=0,
        draft_attempts=0,
        regeneration_attempts=0,
        hitl_mode=hitl_mode,
        trace=[],
        loops_capped=[],
        notes=[],
        retrieval_log=[],
        stubs=stubs or {},
        no_model=no_model,
    )


# ------------------------------------------------------------------------------ read helpers
# Routers must stay trivial, so anything they need to derive lives here and is unit-testable.


def loop_count(state: GraphState, loop_name: str) -> int:
    """How many times `loop_name` has iterated. Raises on an unknown loop, by design."""
    return int(state.get(LOOP_COUNTERS[loop_name], 0) or 0)


def loop_exhausted(state: GraphState, loop_name: str, caps: dict[str, int]) -> bool:
    """`>=`, not `>`: with cap 2 the second completed pass is the last one."""
    return loop_count(state, loop_name) >= int(caps.get(loop_name, 2))


def times_node_ran(state: GraphState, node_name: str) -> int:
    """
    0-based "which pass am I on", counted from the trace -- `@traced` appends after the body
    returns, so a node sees only its previous runs.

    Counted from the trace rather than a per-node counter because `analyse_policy` is re-entered
    by two different loops, and neither loop's counter tells it how many times it has run.
    """
    return sum(1 for entry in state.get("trace", []) or [] if entry.node == node_name)


def below_route_floor(state: GraphState, floors: dict[str, float]) -> bool:
    """
    Floors are per route. 0.60 is fine for ASK_MORE_INFO (whose band is low by design) and
    nowhere near enough for AUTO_RESOLVE, so one global threshold cannot work.
    """
    route = state.get("route")
    if not route:
        return False
    return float(state.get("confidence", 0.0)) < float(floors.get(route, 0.5))


def has_safety_critical_flag(state: GraphState) -> bool:
    if "safety_critical" in state:
        return bool(state["safety_critical"])
    return any(flag.is_critical for flag in state.get("safety_flags", []) or [])


def policy_was_verified(state: GraphState) -> bool:
    analysis = state.get("policy_analysis")
    return bool(analysis and analysis.policy_verified)


def proposals_disagree(state: GraphState) -> bool:
    """
    Both halves had an opinion and they differ.

    `None == None` is the trap: two silences are not agreement, and a ticket nobody could route
    is a different situation from one the rules and the model fought over.
    """
    rule_route, llm_route = state.get("rule_route"), state.get("llm_route")
    return bool(rule_route and llm_route and rule_route != llm_route)


def review_payload(state: GraphState) -> dict[str, Any]:
    """
    Everything a human reviewer needs, flat and JSON-safe.

    Lives here, beside `summarise`, for two reasons. It is the value `hitl_gate` hands to
    `interrupt()`, so a checkpointer has to serialise it -- a Pydantic model or a datetime in
    here fails at resume time, not at build time. And `src/graph/` must not import the review
    service: the dependency runs `app/` -> `src/hitl/` -> `src/graph/`, never back.

    Field choice follows `logging/replay.py::render`: the reviewer reads the decision in the
    order it was made.
    """
    from src.routing.thread_pressure import assess

    ticket = state.get("ticket")
    history = list(state.get("customer_history") or [])
    pressure = assess(ticket, history) if ticket is not None else None

    return {
        "run_id": state.get("run_id"),
        "ticket_id": state.get("ticket_id"),
        "hitl_mode": state.get("hitl_mode"),
        "ticket": {
            "subject": getattr(ticket, "subject", ""),
            "message": getattr(ticket, "message", ""),
            "category": getattr(ticket, "category", ""),
            "product_area": getattr(ticket, "product_area", ""),
            "priority": getattr(ticket, "priority", ""),
            "channel": getattr(ticket, "channel", ""),
            "customer_id": getattr(ticket, "customer_id", ""),
            "created_at": jsonable(getattr(ticket, "created_at", None)),
        },
        # `role` travels with every turn so the screen can mark the `system` ones. They are
        # internal events, and a reviewer skimming reads "Source IP geolocation: inconsistent"
        # as something the customer wrote unless the screen says otherwise.
        "conversation": [
            {"turn": turn.turn, "role": turn.role, "text": turn.text,
             "timestamp": jsonable(turn.timestamp)}
            for turn in getattr(ticket, "conversation_history", []) or []
        ],
        "customer_history": jsonable(history),
        "thread_pressure": (
            {"level": pressure.level, "reason": pressure.reason, **pressure.as_inputs()}
            if pressure is not None
            else {}
        ),
        "sentiment": state.get("sentiment"),
        "intent": state.get("intent"),
        "safety_flags": jsonable(state.get("safety_flags") or []),
        "preconditions": jsonable(state.get("preconditions") or {}),
        "retrieval_mode": state.get("retrieval_mode"),
        "retrieval_log": jsonable(state.get("retrieval_log") or []),
        "retrieved": jsonable(state.get("retrieved") or []),
        "policy_analysis": jsonable(state.get("policy_analysis")),
        "rule_route": state.get("rule_route"),
        "llm_route": state.get("llm_route"),
        "proposals_disagree": proposals_disagree(state),
        "route": state.get("route"),
        "route_rationale": state.get("route_rationale"),
        "escalation_target": state.get("escalation_target"),
        "escalation_visible_to_customer": bool(state.get("escalation_visible_to_customer", True)),
        "confidence": round(float(state.get("confidence", 0.0)), 4),
        "confidence_parts": dict(state.get("confidence_parts") or {}),
        "draft": state.get("draft") or "",
        "cited_policy_ids": list(state.get("cited_policy_ids") or []),
        "validation": jsonable(state.get("validation")),
        "loops": {name: loop_count(state, name) for name in LOOP_COUNTERS},
        "loops_capped": list(state.get("loops_capped") or []),
        "regeneration_attempts": loop_count(state, "review_regeneration"),
    }


def summarise(state: GraphState) -> dict[str, Any]:
    """A flat, JSON-safe view of the outcome, for the run table in `main.py`."""
    return {
        "ticket_id": state.get("ticket_id"),
        "route": state.get("route"),
        "escalation_target": state.get("escalation_target"),
        "confidence": round(float(state.get("confidence", 0.0)), 3),
        "rule_route": state.get("rule_route"),
        "llm_route": state.get("llm_route"),
        "retrieval_mode": state.get("retrieval_mode"),
        "loops_capped": list(state.get("loops_capped", []) or []),
        "reviewer": state["reviewer"].action if state.get("reviewer") else None,
        "nodes_run": [entry.node for entry in state.get("trace", []) or []],
    }
