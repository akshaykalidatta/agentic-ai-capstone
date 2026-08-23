"""
The five routers, and the topology declared as data.

Two rules the routers follow:

1. **Routers choose, nodes write.** A router takes state and returns a string; it never
   mutates. When a loop hits its cap the *node* forces the route and the router only stops
   looping -- otherwise the audit record and the path taken could disagree.
2. **Every branch needs a key for every case.** LangGraph has no default edge; an unmapped
   return value raises at runtime, on ticket 94 of 150.

The topology lives in `EDGES` / `CONDITIONAL_EDGES` / `LOOPS` as plain data so
`tests/test_graph_topology.py` can check it without langgraph installed, and so
`support_graph.build_graph()` is a loop over data rather than twenty near-identical lines.
"""

from __future__ import annotations

from typing import Any, Callable

from src.graph.graph_state import (
    GraphState,
    below_route_floor,
    has_safety_critical_flag,
    loop_exhausted,
    policy_was_verified,
)
from src.utils.config import app_config, routing_rules


def _loop_caps() -> dict[str, int]:
    return app_config().get("graph", {}).get("loop_caps", {}) or {}


def _confidence_floors() -> dict[str, float]:
    return routing_rules().get("route_confidence_floors", {}) or {}


def after_triage(state: GraphState) -> str:
    """
    The bypass branch. Only "does a safety-critical flag exist" -- never "is the customer
    angry". Six tickets are hostile with a legitimate request and must route on the request.
    """
    return "safety" if has_safety_critical_flag(state) else "normal"


def after_analysis(state: GraphState) -> str:
    """
    Loop 1: refine only if the clauses did not settle the question, and only while budget
    remains. When capped, `policy_verified` is still False and `route_decision` escalates --
    which is also how the 8 tickets with no supporting policy get handled.
    """
    if policy_was_verified(state):
        return "route"
    return "refine" if not loop_exhausted(state, "retrieval_refine", _loop_caps()) else "route"


def after_confidence(state: GraphState) -> str:
    """
    Loop 2. The `loops_capped` check comes first and is not redundant: when the node caps out
    it rewrites the route to ESCALATE, whose floor may still be above the confidence that
    caused the cap. Without the guard the ticket re-enters a loop already declared finished.
    """
    if "confidence_recheck" in (state.get("loops_capped") or []):
        return "draft"
    if not below_route_floor(state, _confidence_floors()):
        return "draft"
    return "reconsider" if not loop_exhausted(state, "confidence_recheck", _loop_caps()) else "draft"


def after_validation(state: GraphState) -> str:
    """Loop 3. Same `loops_capped` guard: the bare acknowledgement must not be re-validated."""
    if "draft_repair" in (state.get("loops_capped") or []):
        return "review"
    validation = state.get("validation")
    if validation is None or validation.ok:
        return "review"
    return "repair" if not loop_exhausted(state, "draft_repair", _loop_caps()) else "review"


def after_review(state: GraphState) -> str:
    """
    Six reviewer actions, one re-entry point. Only REQUEST_REGENERATION goes back to drafting;
    the other five are decisions a human has already made and terminate into audit.
    """
    reviewer = state.get("reviewer")
    if reviewer is None:
        return "done"
    if reviewer.action != "REQUEST_REGENERATION":
        return "done"
    # Capped like the other three loops. Without this a reviewer holding the button creates a
    # fourth, undeclared cycle that no counter bounds.
    return "done" if loop_exhausted(state, "review_regeneration", _loop_caps()) else "regenerate"


ROUTERS: dict[str, Callable[[GraphState], str]] = {
    "triage": after_triage,
    "analyse_policy": after_analysis,
    "score_confidence": after_confidence,
    "validate_draft": after_validation,
    "hitl_gate": after_review,
}

EDGES: tuple[tuple[str, str], ...] = (
    ("__start__", "triage"),
    ("preconditions", "retrieve"),
    ("retrieve", "analyse_policy"),
    ("refine_query", "retrieve"),  # loop 1 closes here
    ("route_decision", "score_confidence"),
    ("draft_reply", "validate_draft"),
    ("safety_escalate", "hitl_gate"),  # the bypass rejoins before review, never after
    ("audit_log", "__end__"),
)

CONDITIONAL_EDGES: dict[str, dict[str, str]] = {
    "triage": {"safety": "safety_escalate", "normal": "preconditions"},
    "analyse_policy": {"refine": "refine_query", "route": "route_decision"},
    "score_confidence": {"reconsider": "analyse_policy", "draft": "draft_reply"},  # loop 2
    "validate_draft": {"repair": "draft_reply", "review": "hitl_gate"},  # loop 3
    "hitl_gate": {"regenerate": "draft_reply", "done": "audit_log"},
}

# Declared so the test can assert each cycle has an exit that does not re-enter it.
LOOPS: tuple[dict[str, Any], ...] = (
    {
        "name": "retrieval_refine",
        "router": "analyse_policy",
        "back_edge": ("refine_query", "retrieve"),
        "exit_key": "route",
        "exit_node": "route_decision",
        "capped_behaviour": "policy_verified stays False -> route_decision forces ESCALATE",
    },
    {
        "name": "confidence_recheck",
        "router": "score_confidence",
        "back_edge": ("score_confidence", "analyse_policy"),
        "exit_key": "draft",
        "exit_node": "draft_reply",
        "capped_behaviour": "score_confidence forces ESCALATE or ASK_MORE_INFO",
    },
    {
        "name": "draft_repair",
        "router": "validate_draft",
        "back_edge": ("validate_draft", "draft_reply"),
        "exit_key": "review",
        "exit_node": "hitl_gate",
        "capped_behaviour": "validate_draft forces ESCALATE with a bare acknowledgement",
    },
)
