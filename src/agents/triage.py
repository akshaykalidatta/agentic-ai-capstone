"""
Triage: sentiment, intent, entities, and the model half of safety classification.

Two layers, in this order:

1. `safety.policy_checker` -- deterministic patterns. Auditable, free, cannot be argued out of
   firing. Catches 11 of the 12 prohibited-request tickets and both safety-critical ones, with
   zero false positives across all 150.
2. This module -- one `fast`-model call for what patterns cannot reach: an implied threat,
   abuse inferred from *"my son handles my account now, please don't call the house"*, or an
   employer quietly asking after an employee's deposit (TCK-1085, the one pattern miss).

**The model can only add flags, never remove them.** A deterministic hit is a fact about the
text; letting a model overrule it would put the auditable layer at the mercy of the persuasive
one, which is backwards.

## Degradation

If the model is unreachable -- no API key, Groq down, rate limit exhausted -- triage returns
the deterministic results and records `triage_degraded` in the notes. That is a real operating
mode, not an error path: the pattern layer alone already passes P2's gate.
"""

from __future__ import annotations

import logging
from datetime import date

from pydantic import BaseModel, Field

from src.agents.base import StructuredOutputError, call_structured
from src.safety.policy_checker import is_tone_only, scan_ticket
from src.utils.constants import SENTIMENTS
from src.utils.schemas import SafetyFlag, Ticket

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the triage stage of a bank's support pipeline.

You classify the MESSAGE. You never decide what the bank should do about it. Two rules matter
more than anything else:

1. Hostility, sarcasm, threats to sue, threats to post on social media, and demands to speak
   to a manager are NOT safety concerns. A furious customer with a legitimate request is a
   legitimate request. Never flag one.
2. A safety concern is a threat of physical harm, a disclosure of self-harm, or a welfare
   crisis. These are about the person's safety, not about how rude they were.

Report only what the text supports. Do not infer, speculate, or add flags to be cautious."""


class ExtractedEntities(BaseModel):
    """
    The structured facts hiding in the prose.

    This exists to unblock the rule engine. `fee_within_60_days` cannot be computed from
    `customer_context` -- the fee date lives only in the message -- so until this model
    extracts it, that precondition can only ever return "cannot determine". Every field is
    optional and defaults to None, because a missing fact and a wrong fact are very
    different, and None is what drives ASK_MORE_INFO.
    """

    amount: float | None = Field(None, description="the disputed or charged amount in dollars")
    fee_date: date | None = Field(None, description="date the fee was charged, YYYY-MM-DD")
    transaction_date: date | None = Field(None, description="date of the transaction, YYYY-MM-DD")
    merchant: str | None = Field(None, description="merchant or counterparty name")
    claim_id: str | None = Field(None, description="an existing claim or case reference")
    card_last4: str | None = Field(None, description="last four digits of a card, if stated")
    merchant_contacted: bool | None = Field(
        None, description="true only if the customer says they contacted the merchant"
    )
    transaction_pending: bool | None = Field(
        None, description="true if the customer says the item is still pending"
    )
    fee_reversal_requested: bool | None = Field(
        None,
        description="true ONLY if the customer is asking for a bank fee to be reversed, "
        "waived or refunded. False for merchant disputes, unauthorised charges and "
        "subscription billing -- those are not fee reversals.",
    )

    def as_query_terms(self) -> list[str]:
        """Retrieval wants search terms, not typed fields. Flattened at the seam."""
        terms = [self.merchant, self.card_last4]
        if self.amount:
            terms.append(f"${self.amount:.2f}")
        return [t for t in terms if t]


class TriageResult(BaseModel):
    """What the `fast` model returns."""

    sentiment: str = Field(description=f"exactly one of {list(SENTIMENTS)}")
    intent: str = Field(description="the customer's request in under 12 words, no adjectives")
    entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    hostile_tone: bool = Field(
        description="true if the message is angry, insulting or shouting. Tone only -- this "
        "must never influence whether the request is legitimate."
    )
    additional_safety_codes: list[str] = Field(
        default_factory=list,
        description="ONLY for concerns not already obvious from keywords. Valid values: "
        "THREAT, SELF_HARM, CRISIS_OTHER, FINANCIAL_ABUSE, THIRD_PARTY_ACCESS, "
        "PROHIBITED_REQUEST, INDUCEMENT, STRUCTURING, DISCRIMINATORY. Usually empty.",
    )
    safety_reasoning: str = Field(
        default="", description="one sentence, only if you added a safety code"
    )


def build_prompt(ticket: Ticket) -> str:
    context = ticket.customer_context
    return f"""Classify this support ticket.

SUBJECT: {ticket.subject}
CATEGORY: {ticket.category}   PRODUCT: {ticket.product_area}

CUSTOMER MESSAGE:
\"\"\"
{ticket.message}
\"\"\"
{_history_block(ticket)}
ACCOUNT FACTS (context only -- do not treat as part of the message):
- tenure: {context.tenure_months} months, segment: {context.segment}
- prior tickets (90d): {context.prior_tickets_90d}

Extract sentiment, the intent in a few words, and any dates, amounts or merchant names stated
in the message. Add a safety code only if there is a genuine concern a keyword scan would
miss."""


def _history_block(ticket: Ticket) -> str:
    if not ticket.conversation_history:
        return ""
    # System turns are included and labelled. They are facts the classifier should see -- a
    # denial letter already went out, sign-ins failed from an odd location -- but they are not
    # the customer speaking, and the label is what keeps that distinction.
    return f"\nEARLIER IN THIS THREAD:\n{ticket.transcript()}\n"


def _coerce_sentiment(value: str) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned in SENTIMENTS:
        return cleaned
    # A model that invents "furious" or "upset" should not crash the run. Map onto the
    # dataset's four labels, which are the only ones the evaluator can score.
    mapping = {
        "angry": "angry", "furious": "angry", "hostile": "angry", "irate": "angry",
        "frustrated": "frustrated", "annoyed": "frustrated", "upset": "frustrated",
        "distressed": "distressed", "worried": "distressed", "anxious": "distressed",
        "scared": "distressed", "desperate": "distressed",
        "neutral": "neutral", "calm": "neutral", "positive": "neutral",
    }
    resolved = mapping.get(cleaned, "neutral")
    log.debug("mapped unrecognised sentiment %r -> %r", value, resolved)
    return resolved


def triage_ticket(ticket: Ticket, *, use_model: bool = True) -> dict:
    """
    Returns the triage state update: sentiment, flags, intent, entities.

    Deterministic first, model second, and the model is additive only.
    """
    pattern_flags = scan_ticket(ticket)
    result: TriageResult | None = None
    notes: list[str] = []

    if use_model:
        try:
            result = call_structured(
                build_prompt(ticket), TriageResult, role="fast", system=SYSTEM_PROMPT
            )
        except StructuredOutputError as exc:
            # Degradation, not failure: the pattern layer alone passes P2's gate.
            log.warning("triage model unavailable for %s (%s); patterns only", ticket.ticket_id, exc)
            notes.append("triage_degraded: model unavailable, deterministic layer only")

    flags = list(pattern_flags)
    known_codes = {flag.code for flag in flags}
    if result:
        for code in result.additional_safety_codes:
            code = code.strip().upper()
            if code and code not in known_codes:
                flags.append(
                    SafetyFlag(
                        code=code,
                        severity="high",
                        evidence_span=result.safety_reasoning[:200],
                        detector="model",
                    )
                )
                known_codes.add(code)

    sentiment = _coerce_sentiment(result.sentiment) if result else _fallback_sentiment(ticket)
    entities = result.entities if result else ExtractedEntities()

    if is_tone_only(ticket, pattern_flags):
        # Recorded on purpose. The six tone-trap tickets need this line in the audit trail as
        # much as they need the right route: it shows tone was seen and deliberately not acted
        # on, rather than never noticed.
        notes.append("tone noted, no safety or prohibited-request flag -- route on the request")

    return {
        "sentiment": sentiment,
        "safety_flags": flags,
        "safety_critical": any(flag.is_critical for flag in flags),
        "intent": (result.intent if result else "").strip(),
        "entities": entities.model_dump(mode="json", exclude_none=True),
        "notes": notes,
        "_summary": (
            f"sentiment={sentiment} flags={','.join(f.code for f in flags) or 'none'} "
            f"intent={(result.intent if result else '(none)')[:40]}"
        ),
    }


def _fallback_sentiment(ticket: Ticket) -> str:
    """Shouting and insults, when there is no model. Crude, and only used while degraded."""
    text = f"{ticket.subject} {ticket.message}"
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6:
        return "angry"
    return "neutral"
