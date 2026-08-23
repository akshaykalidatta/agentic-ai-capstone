"""
Policy reasoning and the model's route proposal.

Two calls, kept separate on purpose:

- `analyse` reads the retrieved clauses and reports which ones **decide** the question, which
  merely **constrain** the wording, what facts are missing, and whether policy was verified
  at all. No route, no prose.
- `propose_route` takes that analysis plus the computed preconditions and proposes a route.

Splitting them is what makes HLD D4's disagreement signal meaningful. If one call did both,
the model's route would be reasoning backwards from its own conclusion, and "the rules and the
model disagree" would stop being evidence of a hard case.

## Two failure modes the prompts are written against

**Re-deriving the preconditions.** The rule engine has already computed, from the structured
record, whether this customer had a prior reversal. The model is told these are established
facts and must not be recalculated from the message -- because the message says *"I don't
think I've ever asked before"* and the record says otherwise.

**Asking for facts the ticket already supplied.** Several tickets give date, amount and
merchant and are still ASK_MORE_INFO, because the genuinely missing fact is something else --
whether the merchant was contacted, whether the entry is still pending. So `missing_facts` is
validated against the ticket text before it can drive a route.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from src.agents.base import StructuredOutputError, call_structured, format_context
from src.utils.constants import ROUTES
from src.utils.schemas import (
    ClauseConflict,
    ClauseConstraint,
    ClauseRef,
    PolicyAnalysis,
    Precondition,
    RetrievedChunk,
    Ticket,
)

log = logging.getLogger(__name__)

ANALYSIS_SYSTEM = """You are a bank policy analyst. You read retrieved policy clauses and
report what they say about one ticket. You do not write to customers and you do not decide
what the bank will do.

Rules:
- Only cite clause IDs that appear in the CONTEXT below. Never invent one.
- A clause DECIDES the question if it determines the outcome. A clause CONSTRAINS if it only
  limits what may be said. Keep them apart.
- The PRECONDITIONS are computed facts from the customer's record. Treat them as true. Do not
  re-derive them from the message, which may contradict them.
- If no clause in the context actually addresses this request, say policy_verified is false.
  That is a useful answer, not a failure."""

ROUTING_SYSTEM = """You choose one route for a support ticket.

AUTO_RESOLVE   a clause clearly permits the action and every condition is met
ESCALATE       a specialist must decide, or policy could not be verified
REFUSE         the request itself is prohibited; still offer the legitimate path
ASK_MORE_INFO  a specific fact is genuinely missing and only the customer can supply it

Hard rules:
- Tone never decides a route. An abusive customer with a valid request gets the valid answer.
- Never ASK_MORE_INFO for something the ticket already states.
- If policy could not be verified, ESCALATE. Do not guess a policy.
- Prefer escalation to a confident wrong answer."""


class PolicyAnalysisResponse(BaseModel):
    """Mirrors `schemas.PolicyAnalysis`, with prompt-facing field descriptions."""

    deciding_clauses: list[dict[str, str]] = Field(
        default_factory=list,
        description="[{policy_id, why}] -- clauses that determine the outcome",
    )
    constraining_clauses: list[dict[str, str]] = Field(
        default_factory=list,
        description="[{policy_id, constraint}] -- clauses that only limit what may be said",
    )
    missing_facts: list[str] = Field(
        default_factory=list,
        description="facts needed to decide that the ticket does NOT already state",
    )
    policy_verified: bool = Field(
        description="true only if a retrieved clause actually addresses this request"
    )
    conflicts: list[dict[str, Any]] = Field(
        default_factory=list, description="[{between: [ids], resolution}]"
    )
    self_certainty: float = Field(description="your own confidence, 0.0 to 1.0")


class RouteProposal(BaseModel):
    route: str = Field(description=f"exactly one of {list(ROUTES)}")
    rationale: str = Field(description="one sentence, naming the deciding clause if there is one")
    escalation_target: str | None = Field(
        None, description="internal queue name, only if escalating or opening a file"
    )


def _preconditions_block(preconditions: dict[str, Precondition]) -> str:
    if not preconditions:
        return "(none computed for this ticket)"
    lines = []
    for name, precondition in preconditions.items():
        verdict = {True: "YES", False: "NO", None: "CANNOT DETERMINE"}[precondition.met]
        lines.append(f"- {name}: {verdict} -- {precondition.reason}")
    return "\n".join(lines)


def analyse(
    ticket: Ticket,
    chunks: list[RetrievedChunk],
    preconditions: dict[str, Precondition],
    *,
    disagreement_note: str = "",
    history_block: str = "",
) -> PolicyAnalysis:
    """
    Read the clauses, report what they decide.

    `disagreement_note` is set when the confidence loop re-enters this node. The loop rule is
    that a retry must change an input -- re-running an identical prompt returns an identical
    answer and burns a call -- so the disagreement is stated explicitly and the model is asked
    to look again at that specific tension.
    """
    context = format_context(chunks)
    prompt = f"""TICKET
subject: {ticket.subject}
category: {ticket.category}   product: {ticket.product_area}

message:
\"\"\"
{ticket.message}
\"\"\"

PRECONDITIONS (computed from the customer's record -- treat as established fact)
{_preconditions_block(preconditions)}
{history_block}

CONTEXT (the only clauses you may cite)
{context if context else "(nothing was retrieved)"}
{f"NOTE: {disagreement_note}" if disagreement_note else ""}

Which clauses decide this? Which only constrain the wording? What is genuinely missing?"""

    try:
        response = call_structured(prompt, PolicyAnalysisResponse, system=ANALYSIS_SYSTEM)
    except StructuredOutputError as exc:
        # Unverified policy routes to a human, which is the safe direction to fail in.
        log.warning("policy analysis failed for %s (%s)", ticket.ticket_id, exc)
        return PolicyAnalysis(
            policy_verified=False,
            missing_facts=[],
            self_certainty=0.0,
        )

    retrieved_ids = {chunk.policy_id for chunk in chunks if chunk.policy_id}
    # Drop invented citations here rather than letting them reach the draft. P4's gate is zero
    # hallucinated citations, and a clause filtered at the source cannot be cited later.
    deciding = [
        ClauseRef(policy_id=item.get("policy_id", ""), why=item.get("why", ""))
        for item in response.deciding_clauses
        if item.get("policy_id") in retrieved_ids
    ]
    dropped = len(response.deciding_clauses) - len(deciding)
    if dropped:
        log.warning("%s: dropped %d clause(s) not in the retrieved set", ticket.ticket_id, dropped)

    return PolicyAnalysis(
        deciding_clauses=deciding,
        constraining_clauses=[
            ClauseConstraint(
                policy_id=item.get("policy_id", ""), constraint=item.get("constraint", "")
            )
            for item in response.constraining_clauses
            if item.get("policy_id") in retrieved_ids
        ],
        missing_facts=_validate_missing_facts(response.missing_facts, ticket),
        # A model claiming verification while citing nothing that was retrieved has not
        # verified anything.
        policy_verified=bool(response.policy_verified and deciding),
        conflicts=[
            ClauseConflict(
                between=list(item.get("between", [])), resolution=str(item.get("resolution", ""))
            )
            for item in response.conflicts
        ],
        self_certainty=max(0.0, min(1.0, float(response.self_certainty))),
    )


def _validate_missing_facts(facts: list[str], ticket: Ticket) -> list[str]:
    """
    Drop anything the ticket already answers.

    Cheap check: if the significant words of the "missing" fact already appear in the message,
    the model is asking for something it was given. Re-asking a customer for a date they
    supplied in their first sentence is its own failure mode, and several tickets are labelled
    ASK_MORE_INFO for a genuinely different missing fact.
    """
    text = f"{ticket.subject} {ticket.message}".lower()
    kept: list[str] = []
    for fact in facts:
        words = [w for w in fact.lower().split() if len(w) > 4]
        if words and sum(w in text for w in words) / len(words) > 0.8:
            log.debug("dropping already-supplied missing fact: %r", fact)
            continue
        kept.append(fact)
    return kept


def propose_route(
    ticket: Ticket,
    analysis: PolicyAnalysis,
    preconditions: dict[str, Precondition],
    chunks: list[RetrievedChunk],
    *,
    rule_route: str | None = None,
) -> tuple[str | None, str, str | None]:
    """
    The model's route proposal: `(route, rationale, escalation_target)`.

    `rule_route` is deliberately **not** shown to the model. The whole value of D4 is two
    independent opinions; telling the model what the rules concluded turns the second opinion
    into agreement, and the disagreement signal disappears.
    """
    deciding = ", ".join(analysis.deciding_ids()) or "none"
    prompt = f"""TICKET
subject: {ticket.subject}
category: {ticket.category}   product: {ticket.product_area}

message:
\"\"\"
{ticket.message}
\"\"\"

PRECONDITIONS (established facts, do not re-derive)
{_preconditions_block(preconditions)}

POLICY ANALYSIS
- policy verified: {analysis.policy_verified}
- deciding clauses: {deciding}
- constraints: {[c.constraint for c in analysis.constraining_clauses] or "none"}
- missing facts: {analysis.missing_facts or "none"}
- conflicts: {[c.resolution for c in analysis.conflicts] or "none"}

Choose the route."""

    try:
        proposal = call_structured(prompt, RouteProposal, system=ROUTING_SYSTEM)
    except StructuredOutputError as exc:  # the only failure type call_structured raises
        log.warning("route proposal failed for %s (%s)", ticket.ticket_id, exc)
        return None, f"model proposal unavailable: {exc}", None

    route = proposal.route.strip().upper()
    if route not in ROUTES:
        log.warning("model proposed unknown route %r; treating as no proposal", proposal.route)
        return None, f"model proposed an invalid route {proposal.route!r}", None
    return route, proposal.rationale.strip(), (proposal.escalation_target or None)
