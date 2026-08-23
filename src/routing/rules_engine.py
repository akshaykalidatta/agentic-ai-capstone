"""
The deterministic rule engine: policy preconditions computed from the structured record.

This is the largest single accuracy lever in the project, and it is all arithmetic.

One ticket reads *"I've been with Northgate since 2019 and I don't think I've ever asked for
anything like this before."* The customer's `prior_fee_reversals_12m` is 0, so he is right, and
FEE-001's courtesy reversal applies -> AUTO_RESOLVE. Change that one field to 1 and the correct
answer becomes ESCALATE to Service Recovery under FEE-002, **with the customer's sentence
completely unchanged**. A language model reading that message believes him every time.

So eligibility is computed here, from fields, and handed to the model as established fact it
is told not to re-derive. The rules read **fields, never prose** -- anything that needs to read
the message belongs in `src/agents/`, and that boundary is what makes these thresholds
reviewable by someone who does not read Python.

## Completeness is not the goal

`propose_route` returns `None` whenever no rule fires, and that is a legitimate answer meaning
"no rule covers this ticket" -- the model's proposal then stands unopposed. The rules only have
to be *correct where they fire*. That is what makes the rule-vs-model disagreement a usable
hard-case detector rather than noise.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from src.utils.config import routing_rules
from src.utils.constants import SAFETY_CRITICAL_CODES, Route
from src.utils.schemas import Precondition, SafetyFlag, Ticket

log = logging.getLogger(__name__)


def thresholds() -> dict[str, Any]:
    """
    Numbers live in `config/routing_rules.yaml` so a compliance reviewer can read them without
    reading Python. Changing a threshold must never mean editing a node.
    """
    return routing_rules().get("thresholds", {}) or {}


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
    return None


def compute(
    ticket: Ticket,
    entities: dict[str, Any] | None = None,
    history: list[Any] | None = None,
) -> dict[str, Precondition]:
    """
    Every precondition this ticket's category makes relevant.

    `entities` comes from triage. Preconditions that need a fact only present in the prose --
    a fee date, a disputed amount -- stay indeterminate (`met=None`) until triage supplies it,
    and `met=None` drives ASK_MORE_INFO rather than a guess.
    """
    entities = entities or {}
    context = ticket.customer_context
    limits = thresholds()
    today = ticket.created_at.date()
    out: dict[str, Precondition] = {}

    def add(name: str, met: bool | None, reason: str, **inputs: Any) -> None:
        out[name] = Precondition(name=name, met=met, reason=reason, inputs=inputs)

    # ------------------------------------------------------------------- fees (FEE family)
    #
    # Gated on triage confirming this is actually a fee-reversal request. Without the gate,
    # `prior_fee_reversals_12m > 0` fires FEE-002 on every disputes_and_fees ticket -- and
    # "I need to dispute a charge on my card" is not a courtesy-reversal request at all.
    # That single mistake accounted for 4 of the rule engine's 6 errors.
    if ticket.category == "disputes_and_fees" and entities.get("fee_reversal_requested"):
        prior = context.prior_fee_reversals_12m
        add(
            "no_prior_fee_reversal_12m",
            prior == 0,
            "no courtesy reversal in 12 months -- FEE-001 available"
            if prior == 0
            else f"{prior} prior reversal(s) -- FEE-002, escalate to Service Recovery",
            prior_fee_reversals_12m=prior,
            threshold=0,
        )

        # FEE-001 condition 1 and FEE-006's boundary, from the same date.
        fee_date = _as_date(entities.get("fee_date"))
        window = int(limits.get("fee_reversal_window_days", 60))
        if fee_date is None:
            add(
                "fee_within_60_days",
                None,
                "fee date is not in the structured record and triage did not extract one",
                blocked_on="triage.entities.fee_date",
                window_days=window,
            )
        else:
            age = (today - fee_date).days
            add(
                "fee_within_60_days",
                age <= window,
                f"fee posted {age} days ago (limit {window}) -- "
                + ("within Tier 1 authority" if age <= window else "FEE-006, escalate"),
                fee_date=fee_date.isoformat(),
                age_days=age,
                window_days=window,
            )

    # -------------------------------------------------------------- disputes (DSP family)
    if ticket.category in {"disputes_and_fees", "payments_troubleshooting"}:
        amount = entities.get("amount")
        specialist_amount = float(limits.get("specialist_review_amount", 2500))
        if amount is None:
            add(
                "amount_under_specialist_threshold",
                None,
                "disputed amount not stated in the structured record",
                blocked_on="triage.entities.amount",
                threshold=specialist_amount,
            )
        else:
            add(
                "amount_under_specialist_threshold",
                float(amount) <= specialist_amount,
                f"${float(amount):,.2f} vs ${specialist_amount:,.0f} specialist threshold"
                + ("" if float(amount) <= specialist_amount else " -- DSP-003, Claims Specialist"),
                amount=float(amount),
                threshold=specialist_amount,
            )

        disputes = context.prior_disputes_12m
        dispute_limit = int(limits.get("specialist_review_dispute_count", 3))
        add(
            "under_dispute_count_threshold",
            disputes < dispute_limit,
            f"{disputes} disputes in 12 months (threshold {dispute_limit})"
            + ("" if disputes < dispute_limit else " -- DSP-003, Claims Specialist"),
            prior_disputes_12m=disputes,
            threshold=dispute_limit,
        )

        # DSP-003: a re-opened claim after denial. The trigger is a `system` turn recording
        # that a denial already went out -- a fact no amount of reading the customer's
        # message would reveal (TCK-1044).
        denial_events = [
            turn.text
            for turn in ticket.system_events
            if "denial" in turn.text.lower() or "no error found" in turn.text.lower()
        ]
        add(
            "no_prior_denial_on_this_claim",
            not denial_events,
            "no prior denial on record"
            if not denial_events
            else "a denial was already issued -- DSP-003, re-opened claim",
            system_events=denial_events,
        )

    # --------------------------------------------------- account age (FEE-003) and tenure
    account_age = context.account_age_days
    new_account_days = int(limits.get("new_account_days", 30))
    if account_age is not None:
        add(
            "account_older_than_30_days",
            account_age > new_account_days,
            f"account is {account_age} days old (boundary {new_account_days})",
            account_age_days=account_age,
            threshold=new_account_days,
        )

    # ------------------------------------------------------------------------ Reg E scope
    # Regulation E covers consumer accounts. A Small Business account has no Reg E claim, and
    # telling a business customer they have one is a substantive error (TCK-1091).
    consumer_segments = set(limits.get("reg_e_segments", ["Consumer", "Premier", "Student"]))
    add(
        "regulation_e_applies",
        context.segment in consumer_segments,
        f"segment {context.segment!r} "
        + ("is covered by Reg E" if context.segment in consumer_segments
           else "is not a consumer account -- Reg E does not apply"),
        segment=context.segment,
        covered_segments=sorted(consumer_segments),
    )

    # ---------------------------------------------------------------------- thread pressure
    # Recorded as a precondition even though it forces nothing below level 2, so the audit
    # record shows the thread was considered rather than leaving the reader to wonder.
    from src.routing.thread_pressure import assess

    pressure = assess(ticket, list(history or []))
    add(
        "thread_not_under_pressure",
        pressure.level < 2,
        pressure.reason,
        level=pressure.level,
        **pressure.as_inputs(),
    )

    # ------------------------------------------------------------------------ verification
    add(
        "identity_verified",
        context.kyc_verified,
        "KYC verified" if context.kyc_verified else "KYC not verified -- cannot act on account",
        kyc_verified=context.kyc_verified,
    )

    return out


def propose_route(
    ticket: Ticket,
    preconditions: dict[str, Precondition],
    safety_flags: list[SafetyFlag],
) -> tuple[Route | None, str]:
    """
    The rule engine's route proposal, and why. `None` means no rule covered this ticket.

    Evaluated most-specific first. Safety outranks everything, then prohibited requests, then
    the fee and dispute ladders. A rule only fires when its inputs are *determinate* -- an
    indeterminate precondition contributes nothing rather than defaulting to False.
    """
    codes = {flag.code for flag in safety_flags}

    if codes & set(SAFETY_CRITICAL_CODES):
        critical = sorted(codes & set(SAFETY_CRITICAL_CODES))[0]
        return "ESCALATE", f"safety-critical flag {critical}"

    # Prohibited requests refuse. The service request underneath does not disappear -- the
    # draft still has to offer the legitimate path -- but the framing is declined.
    # A customer reporting exploitation of their own account is a dispute, not a prohibited
    # request. DSP-003 routes it to a Claims Specialist with elder-abuse screening, and this
    # branch has to come BEFORE the refusal codes or an 81-year-old victim gets declined.
    if "FINANCIAL_ABUSE" in codes:
        return "ESCALATE", "DSP-003 family member named in an unauthorised-activity report"

    refusal_codes = {
        "PROHIBITED_REQUEST", "INDUCEMENT", "STRUCTURING", "DISCRIMINATORY",
        "SEXUAL_CONTENT", "THIRD_PARTY_ACCESS", "PROMPT_INJECTION",
    }
    if codes & refusal_codes:
        return "REFUSE", f"prohibited request: {', '.join(sorted(codes & refusal_codes))}"

    if _is_false(preconditions.get("identity_verified")):
        return "ASK_MORE_INFO", "identity not verified"

    # Deliberately AFTER safety and refusal. TCK-1109 has two prior escalations and is still a
    # REFUSE -- a prohibited request stays prohibited however hard the thread is pushing.
    if _is_false(preconditions.get("thread_not_under_pressure")):
        return "ESCALATE", "thread pressure: repeatedly escalated, not converging"

    # DSP-003 -- any one of these sends the claim to a specialist.
    for name, clause in (
        ("amount_under_specialist_threshold", "DSP-003 amount threshold"),
        ("under_dispute_count_threshold", "DSP-003 dispute-count threshold"),
        ("no_prior_denial_on_this_claim", "DSP-003 re-opened claim"),
    ):
        if _is_false(preconditions.get(name)):
            return "ESCALATE", clause

    # FEE-006 before FEE-002: an out-of-window fee escalates regardless of reversal history.
    if _is_false(preconditions.get("fee_within_60_days")):
        return "ESCALATE", "FEE-006 fee older than 60 days"
    if _is_false(preconditions.get("no_prior_fee_reversal_12m")):
        return "ESCALATE", "FEE-002 repeat reversal request"

    # A fee request that clears every determinate check is the FEE-001 courtesy reversal.
    fee_checks = ("no_prior_fee_reversal_12m", "fee_within_60_days")
    if all(_is_true(preconditions.get(name)) for name in fee_checks):
        return "AUTO_RESOLVE", "FEE-001 all conditions met"

    return None, "no deterministic rule covers this ticket"


def _is_true(precondition: Precondition | None) -> bool:
    return precondition is not None and precondition.met is True


def _is_false(precondition: Precondition | None) -> bool:
    """
    Strictly False. `None` (not determinable) must never read as False -- that would assert
    "the fee is older than 60 days" about every fee ticket whose date triage could not find.
    """
    return precondition is not None and precondition.met is False


def determinacy(preconditions: dict[str, Precondition]) -> float:
    """
    Fraction of preconditions that resolved either way. Feeds the confidence score: a ticket
    whose rules could not be evaluated is a ticket we know less about.
    """
    if not preconditions:
        return 0.0
    determinate = sum(1 for p in preconditions.values() if p.met is not None)
    return round(determinate / len(preconditions), 4)
