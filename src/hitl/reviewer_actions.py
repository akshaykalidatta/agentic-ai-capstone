"""
The six reviewer actions and what each does to the run.

Data rather than a chain of `if action == ...`, because three places need the same answers:
`graph.edges.after_review` (does this re-enter the graph?), the audit record (is this a route
override?), and P7's UI.

The distinction worth reading: EDIT does not regenerate. A reviewer who rewrote the draft has
already produced the answer; sending it back discards human work and costs a call.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.utils.constants import REVIEWER_ACTIONS, ReviewerAction


@dataclass(frozen=True)
class ActionSpec:
    action: str
    label: str
    reenters_graph: bool
    counts_as_route_override: bool
    description: str


ACTIONS: dict[str, ActionSpec] = {
    "APPROVE": ActionSpec(
        "APPROVE", "Approve", False, False,
        "Draft is correct as written. Terminates into audit.",
    ),
    "APPROVE_AND_ROUTE": ActionSpec(
        "APPROVE_AND_ROUTE", "Approve and route", False, False,
        "Correct, and the case goes to the named internal queue. The default for every "
        "ESCALATE and for the 7 REFUSE tickets that still open a file.",
    ),
    "EDIT": ActionSpec(
        "EDIT", "Edit and approve", False, False,
        "Reviewer rewrote the reply. Both versions are kept -- edit size is a quality signal.",
    ),
    "REQUEST_REGENERATION": ActionSpec(
        "REQUEST_REGENERATION", "Send back for regeneration", True, False,
        "The only action that re-enters the graph. The comment becomes a drafting input.",
    ),
    "REJECT": ActionSpec(
        "REJECT", "Reject", False, False,
        "Nothing goes out and nothing is regenerated. A human takes the ticket over.",
    ),
    "ESCALATE_OVERRIDE": ActionSpec(
        "ESCALATE_OVERRIDE", "Override: escalate", False, True,
        "Reviewer escalates a ticket the agent did not. Override rate is a quality signal.",
    ),
}

assert set(ACTIONS) == set(REVIEWER_ACTIONS), "ACTIONS and constants.ReviewerAction disagree"


def spec(action: ReviewerAction | str) -> ActionSpec:
    if action not in ACTIONS:
        raise KeyError(f"unknown reviewer action {action!r}; have {sorted(ACTIONS)}")
    return ACTIONS[action]
