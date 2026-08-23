"""
Case history turned into a routing signal (HLD §6).

Four customers in the dataset appear as one escalating story. The clearest is CUST-0022:

    TCK-1044  denied dispute            -> ESCALATE, Claims Specialist
    TCK-1095  "close my account"        -> ESCALATE, Deposit Operations
    TCK-1109  "give me the rep's name"  -> REFUSE,   Conduct Review
    TCK-1125  "I've retained counsel"   -> ESCALATE, Executive Complaints

Read TCK-1125 alone and it is a moderately angry customer. Read it after the other three and
it is a regulatory-risk case that belongs with Executive Complaints, not Claims.

## Pressure hardens routing; it never overrides it

The naive rule -- "a repeat contact after a resolved ticket escalates" -- breaks on CUST-0041,
whose second ticket (TCK-1142) is a genuinely new request about the same merchant and stays
AUTO_RESOLVE. And a rule keyed on prior escalations alone breaks TCK-1109, which has two of
them and is still a REFUSE, because a prohibited request stays prohibited however many times
you have been escalated before.

So this module produces a *level*, and the rule engine consults it **after** safety and
refusal have already had their say:

| Level | Meaning | Effect |
| --- | --- | --- |
| 0 | first contact | none |
| 1 | returning after something was marked resolved | exposed as a fact to the model; no forced route |
| 2+ | repeatedly escalated already | forces ESCALATE, and raises the target |

Level 1 deliberately forces nothing. It is the signal that a previous resolution did not hold,
which is real evidence, but not evidence strong enough to overrule what the ticket actually
asks for.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.utils.config import routing_rules
from src.utils.schemas import CaseSummary, Ticket

# Dispositions that mean "we told this customer it was handled".
RESOLVED_DISPOSITIONS = frozenset({"resolved", "closed", "completed"})
ESCALATED_DISPOSITIONS = frozenset({"escalated", "closed_declined", "denied", "rejected"})


@dataclass(frozen=True)
class ThreadPressure:
    level: int
    prior_contacts: int
    prior_escalations: int
    returned_after_resolution: bool
    reason: str

    def as_inputs(self) -> dict[str, object]:
        """Everything the verdict was computed from, for the audit record."""
        return {
            "prior_contacts": self.prior_contacts,
            "prior_escalations": self.prior_escalations,
            "returned_after_resolution": self.returned_after_resolution,
        }


def assess(ticket: Ticket, history: list[CaseSummary]) -> ThreadPressure:
    """Turn the customer's earlier tickets into a pressure level."""
    if not history:
        return ThreadPressure(0, 0, 0, False, "first contact from this customer")

    escalations = sum(
        1
        for entry in history
        if entry.route == "ESCALATE" or entry.disposition in ESCALATED_DISPOSITIONS
    )
    resolved_before = any(entry.disposition in RESOLVED_DISPOSITIONS for entry in history)

    if escalations >= 2:
        return ThreadPressure(
            2, len(history), escalations, resolved_before,
            f"{escalations} prior escalations on this customer -- the thread is not converging",
        )
    if resolved_before:
        return ThreadPressure(
            1, len(history), escalations, resolved_before,
            "a previous ticket was marked resolved and the customer is back",
        )
    return ThreadPressure(
        1 if escalations else 0, len(history), escalations, False,
        f"{len(history)} prior contact(s), {escalations} escalated",
    )


def escalation_target_for(pressure: ThreadPressure, default_target: str | None) -> str | None:
    """
    A thread that has already been escalated twice goes somewhere different.

    Sending TCK-1125 back to Claims Specialist -- the queue that produced the denial it is
    complaining about -- is how a complaint becomes a regulatory filing. The target lives in
    `routing_rules.yaml` so it is changeable without touching a node.
    """
    if pressure.level < 2:
        return default_target
    rules = routing_rules().get("thread_pressure", {}) or {}
    return rules.get("escalated_thread_target", "Executive Complaints")


def context_block(history: list[CaseSummary], pressure: ThreadPressure) -> str:
    """
    The history as the model should see it: dispositions, not our previous reasoning.

    Feeding the agent its own earlier *decisions* compounds one mistake across a thread, each
    step corroborated by the last. Dispositions are facts; decisions are opinions.
    """
    if not history:
        return ""
    lines = [
        f"- {entry.created_at.date()} {entry.ticket_id}: {entry.subject} -> {entry.disposition}"
        + (f" ({entry.escalation_target})" if entry.escalation_target else "")
        for entry in history
    ]
    return (
        "EARLIER TICKETS FROM THIS CUSTOMER (established facts)\n"
        + "\n".join(lines)
        + f"\nThread pressure: level {pressure.level} -- {pressure.reason}"
    )
