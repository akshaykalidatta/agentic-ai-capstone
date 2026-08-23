"""
Drafting: turn a decided route into a reply, and check the reply before it reaches a reviewer.

The route is an **input** here, never an output. Drafting before routing makes the draft the
evidence for the route -- the model writes something helpful, reads its own prose, and
concludes AUTO_RESOLVE because the answer sounds resolved. On the 45 hard tickets that failure
is near-total.

## Four things the prompts enforce

- **Cite only what was retrieved.** `validate_draft` checks this mechanically afterwards, but
  a draft that never invents a clause needs no repair pass.
- **Never quote an internal clause.** CON-010 is a drafting standard for staff. Quoting it at
  a customer is both a citation error and a strange reply.
- **Never promise an outcome or a date.** DSP-006 and the golden set's `must_not_contain` both
  forbid it, and it is the most common thing a helpful model does unprompted.
- **A refusal still offers the legitimate path.** A bare "no" that strands a customer with a
  valid underlying claim is its own failure, and 12 tickets test exactly that.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field

from src.agents.base import StructuredOutputError, call_structured, format_context
from src.utils.schemas import PolicyAnalysis, RetrievedChunk, Ticket

log = logging.getLogger(__name__)

DRAFTING_SYSTEM = """You write replies for a bank's support team. A human reviews everything
you write before it is sent; nothing you produce reaches a customer directly.

Absolute rules:
- Cite only clause IDs listed as CITABLE. Never invent one, never cite an INTERNAL clause.
- Never promise a specific outcome, credit, refund or resolution date.
- Never state or imply how fraud detection, review triggers or verification work.
- Never ask for a full password, one-time passcode, full SSN or card CVV.
- Never mention an internal referral marked as not visible to the customer.
- Match the customer's register but never their hostility. Do not scold, lecture, or comment
  on their tone.
- Plain language. No corporate padding. 120 words or fewer unless the route needs more."""

# What each route's reply is actually for. Kept as data so P4's prompt work is one dict edit.
ROUTE_INSTRUCTIONS: dict[str, str] = {
    "AUTO_RESOLVE": (
        "State what you are doing and the clause that permits it. Confirm the action in "
        "concrete terms without promising a date it will appear."
    ),
    "ESCALATE": (
        "Acknowledge the issue in one or two sentences and say it is going to a specialist "
        "team. Do NOT state or hint at a likely outcome. Do not explain the internal criteria "
        "that sent it there. Keep it short -- this is not the place to explain policy."
    ),
    "REFUSE": (
        "Decline the specific thing that was asked, in one sentence, without moralising. Then "
        "offer the legitimate route to what the customer actually needs. A bare refusal that "
        "leaves a valid request unaddressed is a failure."
    ),
    "ASK_MORE_INFO": (
        "Ask only for the facts listed as missing. Do not re-ask for anything already in the "
        "message. Say briefly why each is needed, and keep the list short."
    ),
}

# For the 8 tickets no clause covers. Escalating silently scores as wrong on those tickets:
# the golden set requires the route AND the sentence, because a customer escalated with no
# explanation has been told nothing.
UNVERIFIED_POLICY_INSTRUCTION = (
    "No policy clause was found that covers this request. You MUST say plainly that we could "
    "not verify a policy covering it and that it is going to a specialist to confirm. Do not "
    "invent a policy, and do not imply the answer is no."
)

SAFETY_BYPASS_DRAFT = (
    "Thank you for telling us. A member of our team will contact you directly and shortly. "
    "We are not able to resolve this over this channel, and we want to make sure you speak "
    "with someone who can help."
)


class DraftResponse(BaseModel):
    body: str = Field(description="the reply to the customer, plain text, no salutation block")
    cited_policy_ids: list[str] = Field(
        default_factory=list, description="clause IDs actually referenced in the body"
    )


def draft(
    ticket: Ticket,
    route: str,
    chunks: list[RetrievedChunk],
    analysis: PolicyAnalysis,
    *,
    sentiment: str = "neutral",
    escalation_visible: bool = True,
    reviewer_comment: str = "",
    repair_note: str = "",
) -> tuple[str, list[str]]:
    """
    Returns `(body, cited_policy_ids)`.

    `repair_note` is set when the validation loop re-enters this node, and `reviewer_comment`
    when a human sent it back. Both change the prompt, because a retry that changes nothing
    returns the same draft and spends the loop budget for free.
    """
    citable = [c for c in chunks if c.citable and c.policy_id]
    internal = [c for c in chunks if not c.citable and c.policy_id]

    unverified = "" if analysis.policy_verified else f"\n{UNVERIFIED_POLICY_INSTRUCTION}"
    prompt = f"""Write the reply.

ROUTE: {route}
{ROUTE_INSTRUCTIONS.get(route, "")}{unverified}

CUSTOMER MESSAGE:
\"\"\"
{ticket.message}
\"\"\"

CUSTOMER TONE: {sentiment} -- adjust register only; it does not change what you tell them.

DECIDING CLAUSES: {", ".join(analysis.deciding_ids()) or "none"}
CONSTRAINTS YOU MUST OBEY: {[c.constraint for c in analysis.constraining_clauses] or "none"}
MISSING FACTS: {analysis.missing_facts or "none"}

CITABLE CLAUSES (you may name these):
{format_context(citable) if citable else "(none -- do not cite anything)"}

INTERNAL GUIDANCE (follow it, never quote or name it): {[c.policy_id for c in internal] or "none"}
{"" if escalation_visible else chr(10) + "An internal referral is being made. Do NOT mention it in any form."}
{f"{chr(10)}REVIEWER ASKED FOR A CHANGE: {reviewer_comment}" if reviewer_comment else ""}
{f"{chr(10)}PREVIOUS DRAFT WAS REJECTED: {repair_note}. Fix exactly this." if repair_note else ""}"""

    try:
        response = call_structured(prompt, DraftResponse, system=DRAFTING_SYSTEM)
    except StructuredOutputError as exc:
        # A draft that cannot be produced is not a draft that gets guessed. The caller
        # escalates with a bare acknowledgement.
        log.warning("drafting failed for %s (%s)", ticket.ticket_id, exc)
        raise

    allowed = {c.policy_id for c in citable}
    cited = [pid for pid in response.cited_policy_ids if pid in allowed]
    # Also catch clause IDs written into the prose but omitted from the list -- the validator
    # scores what is in the body, not what the model remembered to declare.
    for match in re.findall(r"\b[A-Z]{3}-\d{3}\b", response.body):
        if match not in cited:
            cited.append(match)
    return response.body.strip(), cited


def draft_safety_bypass(ticket: Ticket) -> tuple[str, list[str]]:
    """
    The reply for a safety-critical ticket. Fixed text, no model call, no policy.

    Deliberately not generated. The abusive-content policy requires a short human reply and
    forbids pairing a policy quote with a crisis disclosure, and the surest way to honour that
    is to have no policy in the context and no model in the loop.
    """
    return SAFETY_BYPASS_DRAFT, []


# ------------------------------------------------------------------------ content validation

# Deterministic checks only. The semantic half of `must_not_contain` ("promises a specific
# outcome") needs a judge, and an unvalidated judge is a random number generator with good
# manners -- so those land in P8 with hand-labelled validation, not here.
PROHIBITED_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"\b(your (full )?password|one[- ]time (pass)?code|\botp\b|full ssn|social security "
        r"number|security code on the back|\bcvv\b)\b",
        "asks for a credential we must never request",
    ),
    (
        r"\b(guarantee|guaranteed|i promise|we promise|will definitely|you will receive)\b",
        "promises an outcome",
    ),
    (
        r"\b(within \d+ (business )?days? (you|the (refund|credit))|by (monday|tuesday|wednesday|"
        r"thursday|friday|next week))\b",
        "commits to a resolution date",
    ),
    (
        r"\b(flagged (because|by)|triggered (our|the) (rule|threshold|filter)|our system flags"
        r"|fraud (rules?|model|filter) (looks|checks))\b",
        "explains detection logic",
    ),
    (
        r"\b(permanently non-refundable|cannot ever be refunded|will never be reversed)\b",
        "states a final denial the agent is not authorised to make",
    ),
)


def scan_draft(body: str) -> list[str]:
    """Deterministic prohibited-content scan. Returns one description per violation."""
    return [
        description
        for pattern, description in PROHIBITED_PATTERNS
        if re.search(pattern, body, re.IGNORECASE)
    ]
