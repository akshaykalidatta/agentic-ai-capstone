"""
The evaluators, and audit replayability.

    python -m pytest tests/test_evaluation.py -v

These score audit records, so they need no model and no index -- which is the point: a run can
be re-scored months later, or re-scored after changing an evaluator, without spending a call.
"""

from __future__ import annotations

import pytest

from src.evaluation.evaluators import (
    citation_eval,
    confidence_eval,
    groundedness_eval,
    no_policy_eval,
    safety_eval,
)
from src.logging.replay import missing_evidence, render
from src.utils.config import resolve
from src.utils.schemas import load_golden


@pytest.fixture(scope="module")
def labels():
    return load_golden(resolve("data/evaluation/golden_dataset.json"))


# Must be a ticket that HAS a golden record. TCK-1143 is not one of the 107, and using it
# meant every evaluator scored an empty set -- which returns 0.0 and is indistinguishable from
# a real failure. Three of these tests passed for that reason before it was caught.
GOLDEN_TICKET = "TCK-1001"


def record(ticket_id=GOLDEN_TICKET, **overrides):
    """A minimal but complete audit record. Overrides replace whole keys."""
    base = {
        "run_id": "test",
        "ticket_id": ticket_id,
        "route": "AUTO_RESOLVE",
        "route_rationale": "FEE-001 conditions met",
        "config_hash": "abc123",
        "confidence": 0.88,
        "confidence_parts": {"retrieval_strength": 0.9},
        "trace": [{"node": "triage"}],
        "retrieval_mode": "bm25",
        "retrieval_log": [{"attempt": 1, "query": "q", "top_similarity": 0.8}],
        "preconditions": {
            "no_prior_fee_reversal_12m": {
                "met": True, "reason": "none in 12m", "inputs": {"prior_fee_reversals_12m": 0}
            }
        },
        "retrieved": [{"policy_id": "FEE-001", "citable": True}],
        "cited_policy_ids": ["FEE-001"],
        "draft": "We have reversed the fee under FEE-001.",
        "escalation_visible_to_customer": True,
        "escalation_target": None,
    }
    base.update(overrides)
    return base


# ----------------------------------------------------------------------------- groundedness


def test_a_claim_whose_clause_was_not_retrieved_is_unsupported(labels):
    ticket_id = next(t for t, l in labels.items()
                     if any(c.policy_id for c in l.grounding_claims_required))
    result = groundedness_eval([record(ticket_id, retrieved=[])], labels)
    assert result.n > 0, "scored an empty set -- 0.0 here would mean nothing"
    assert result.score == 0.0


def test_action_claims_are_counted_unscored_not_passed(labels):
    """
    Claims with `policy_id: null` are about what we did, not which clause said so. Counting
    them as passes would inflate groundedness with things it cannot actually check.
    """
    ticket_id = next(t for t, l in labels.items()
                     if any(c.policy_id is None for c in l.grounding_claims_required))
    result = groundedness_eval([record(ticket_id)], labels)
    assert result.unscored >= 1


# -------------------------------------------------------------------------------- citations


def test_a_hallucinated_citation_fails_the_gate(labels):
    result = citation_eval(
        [record(cited_policy_ids=["FEE-999"], retrieved=[{"policy_id": "FEE-001", "citable": True}])],
        labels,
    )
    assert result.n > 0
    assert result.score == 0.0
    assert result.gate == 1.0  # zero tolerance; P4's gate is not a percentage


def test_quoting_an_internal_clause_is_a_citation_failure(labels):
    """CON-010 is retrievable and injectable, and quoting it at a customer is a bad reply."""
    result = citation_eval(
        [record(cited_policy_ids=["CON-010"],
                retrieved=[{"policy_id": "CON-010", "citable": False}])],
        labels,
    )
    assert result.score == 0.0
    assert "internal" in result.failures[0]


def test_an_off_list_but_real_citation_is_reported_not_failed(labels):
    """
    A correct reply may name a clause the labeller did not list. Worth counting, not worth
    failing a gate over -- otherwise the gate punishes being more thorough than the label.
    """
    result = citation_eval(
        [record(cited_policy_ids=["FEE-004"],
                retrieved=[{"policy_id": "FEE-004", "citable": True}])],
        labels,
    )
    assert result.score == 1.0
    assert result.detail["off_list_citations"] >= 1


# ----------------------------------------------------------------------------------- safety


def test_asking_for_a_credential_is_caught(labels):
    result = safety_eval([record(draft="Please confirm the one-time passcode we sent.")], labels)
    assert result.n > 0
    assert result.score == 0.0


def test_naming_an_invisible_referral_is_caught(labels):
    """
    No regex in `must_not_contain` covers this -- it depends on state, not wording. TCK-1078
    is the case: naming the referral warns the person the customer needs protecting from.
    """
    result = safety_eval(
        [record(draft="I've referred this to Conduct Review.",
                escalation_visible_to_customer=False, escalation_target="Conduct Review")],
        labels,
    )
    assert result.score == 0.0
    assert "invisible referral" in result.failures[0]


def test_semantic_prohibitions_are_reported_unscored(labels):
    """
    Most `must_not_contain` entries need a judge. Counting them as passes would report full
    coverage from a partial check -- an unvalidated judge is worse than an honest gap.
    """
    result = safety_eval([record()], labels)
    assert result.unscored > 0


# ------------------------------------------------------------------------------- confidence


def test_confidence_outside_the_expected_band_is_flagged(labels):
    ticket_id = next(iter(labels))
    low, high = labels[ticket_id].expected_confidence_band
    result = confidence_eval([record(ticket_id, confidence=min(0.99, high + 0.5))], labels)
    assert result.n > 0
    assert result.score == 0.0 or high >= 0.99


def test_calibration_is_reported_by_decile(labels):
    ticket_id = next(iter(labels))
    result = confidence_eval([record(ticket_id, confidence=0.85)], labels)
    assert "0.8-0.9" in result.detail["calibration_by_decile"]


# -------------------------------------------------------------------------------- no policy


def test_no_policy_needs_both_the_route_and_the_sentence(labels):
    """
    Escalating silently scores as wrong on these 8. A customer escalated with no explanation
    has been told nothing.
    """
    ticket_id = next(t for t, l in labels.items() if l.no_policy_in_kb)

    escalated_only = no_policy_eval(
        [record(ticket_id, route="ESCALATE", draft="A specialist will follow up.")], labels
    )
    assert escalated_only.n > 0
    assert escalated_only.score == 0.0
    assert "does not say" in escalated_only.failures[0]

    both = no_policy_eval(
        [record(ticket_id, route="ESCALATE",
                draft="We could not verify a policy covering this, so it is going to a specialist.")],
        labels,
    )
    assert both.score == 1.0


def test_the_unverifiable_phrasing_matches_real_drafts(labels):
    """
    Regression. The first version of this pattern ended in `\\b` after `verif`, so it could
    not match "verify" -- the evaluator reported 0.000 while every draft was correct.
    """
    ticket_id = next(t for t, l in labels.items() if l.no_policy_in_kb)
    for phrasing in (
        "We could not verify a policy that covers this request.",
        "We were unable to confirm a policy covering this.",
        "There is no published policy for this, so a specialist will confirm.",
    ):
        result = no_policy_eval([record(ticket_id, route="ESCALATE", draft=phrasing)], labels)
        assert result.score == 1.0, phrasing


# --------------------------------------------------------------------------- replayability


def test_a_complete_record_is_replayable():
    assert missing_evidence(record()) == []
    assert "replayable: YES" in render(record())


def test_a_verdict_without_its_inputs_is_not_evidence():
    """
    The specific failure this check exists for: the field is present and looks fine.
    "Eligible" is an assertion; "eligible, no prior reversal in 12 months" is evidence.
    """
    gaps = missing_evidence(
        record(preconditions={"x": {"met": True, "reason": "because", "inputs": {}}})
    )
    assert any("inputs" in g for g in gaps)


def test_a_bypassed_ticket_is_not_penalised_for_having_no_retrieval():
    """
    The safety bypass has no retrieval log and no preconditions by design. Reporting that as a
    broken audit record is how a check trains people to ignore it.
    """
    bypassed = record(
        retrieval_mode="bypassed", retrieval_log=[], preconditions={}, retrieved=[],
        safety_flags=[{"code": "THREAT", "detector": "pattern"}],
    )
    assert missing_evidence(bypassed) == []


def test_a_bypass_that_leaked_policy_text_is_caught():
    """If this ever fires, a crisis reply was drafted with fee clauses in the context window."""
    leaked = record(
        retrieval_mode="bypassed", retrieval_log=[], preconditions={},
        retrieved=[{"policy_id": "FEE-001", "citable": True}],
        safety_flags=[{"code": "THREAT"}],
    )
    assert any("bypass leaked" in g for g in missing_evidence(leaked))
