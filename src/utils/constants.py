"""
Closed vocabularies. Every list here is also a label in `data/evaluation/`, so a typo here
makes a metric silently measure nothing. `tests/test_schemas.py` asserts they match.
"""

from __future__ import annotations

from typing import Literal, get_args

Route = Literal["AUTO_RESOLVE", "ESCALATE", "REFUSE", "ASK_MORE_INFO"]
ROUTES: tuple[str, ...] = get_args(Route)

Sentiment = Literal["neutral", "frustrated", "angry", "distressed"]
SENTIMENTS: tuple[str, ...] = get_args(Sentiment)

Difficulty = Literal["easy", "moderate", "hard"]
DIFFICULTIES: tuple[str, ...] = get_args(Difficulty)

Category = Literal[
    "disputes_and_fees",
    "payments_troubleshooting",
    "digital_access",
    "account_servicing_and_closure",
    "conduct_and_prohibited",
]
CATEGORIES: tuple[str, ...] = get_args(Category)

Priority = Literal["low", "medium", "high", "urgent"]
PRIORITIES: tuple[str, ...] = get_args(Priority)

Severity = Literal["low", "medium", "high", "critical"]

SafetyCode = Literal[
    "THREAT",
    "SELF_HARM",
    "FINANCIAL_ABUSE",
    "CRISIS_OTHER",
    "PROHIBITED_REQUEST",
    "INDUCEMENT",
    "STRUCTURING",
    "DISCRIMINATORY",
    "SEXUAL_CONTENT",
    "THIRD_PARTY_ACCESS",
    "PROMPT_INJECTION",
]

# Membership means three things at once: skip retrieval, never REFUSE, always ESCALATE.
#
# FINANCIAL_ABUSE is deliberately NOT here, and the dataset is why. Two tickets involve
# suspected exploitation and they need opposite handling:
#
#   TCK-1055  an 81-year-old reports her daughter taking money -> ESCALATE, Claims Specialist.
#             The customer is the victim asking for help; this is a dispute, and it routes
#             through normal retrieval like one.
#   TCK-1078  someone asks to see their girlfriend's separate account -> REFUSE the access
#             request, and refer for abuse review silently. The requester may be the abuser.
#
# A bypass forces ESCALATE, so putting FINANCIAL_ABUSE in this tuple makes TCK-1078
# unrepresentable. It is instead a flag that sets a silent escalation target alongside
# whatever route the request itself earns.
SAFETY_CRITICAL_CODES: tuple[str, ...] = ("THREAT", "SELF_HARM", "CRISIS_OTHER")

ReviewerAction = Literal[
    "APPROVE",
    "APPROVE_AND_ROUTE",
    "EDIT",
    "REQUEST_REGENERATION",
    "REJECT",
    "ESCALATE_OVERRIDE",
]
REVIEWER_ACTIONS: tuple[str, ...] = get_args(ReviewerAction)

# The only two the golden set labels. There is no ground truth for "a human would have edited".
GOLDEN_REVIEWER_ACTIONS: tuple[str, ...] = ("APPROVE", "APPROVE_AND_ROUTE")

HitlMode = Literal["interactive", "simulate", "auto"]
HITL_MODES: tuple[str, ...] = get_args(HitlMode)

# Loop name -> the state key counting its passes. Both spellings must agree.
LOOP_COUNTERS: dict[str, str] = {
    "retrieval_refine": "retrieval_attempts",
    "confidence_recheck": "recheck_attempts",
    "draft_repair": "draft_attempts",
    "review_regeneration": "regeneration_attempts",
}

NODE_NAMES: tuple[str, ...] = (
    "triage",
    "preconditions",
    "retrieve",
    "refine_query",
    "analyse_policy",
    "route_decision",
    "score_confidence",
    "draft_reply",
    "validate_draft",
    "safety_escalate",
    "hitl_gate",
    "audit_log",
)
