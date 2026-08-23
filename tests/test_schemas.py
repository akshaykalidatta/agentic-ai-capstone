"""
P0's gate as a test: all 150 tickets parse with zero validation errors.

The count only means something if parsing can fail, so these also pin the two things that make
it real -- the vocabularies in `constants.py` match the labels in `data/evaluation/`, and the
strict/permissive split across the input models is the one that was intended.

    python -m pytest tests/test_schemas.py -v
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.utils.config import resolve
from src.utils.constants import (
    CATEGORIES,
    DIFFICULTIES,
    GOLDEN_REVIEWER_ACTIONS,
    PRIORITIES,
    ROUTES,
    SENTIMENTS,
)
from src.utils.schemas import (
    Ticket,
    load_expected_routes,
    load_golden,
    load_tickets,
    load_tickets_from_records,
)

TICKETS = "data/tickets/synthetic_tickets.json"
SAMPLE = "data/tickets/sample_ticket_batch.json"
GOLDEN = "data/evaluation/golden_dataset.json"
ROUTE_LABELS = "data/evaluation/expected_routes.json"


@pytest.fixture(scope="module")
def tickets():
    return load_tickets(resolve(TICKETS))


@pytest.fixture(scope="module")
def golden():
    return load_golden(resolve(GOLDEN))


# ------------------------------------------------------------------------------- the gate


def test_all_150_tickets_parse(tickets):
    assert len(tickets) == 150


def test_sample_batch_parses():
    assert len(load_tickets(resolve(SAMPLE))) == 13


def test_all_107_golden_records_parse(golden):
    assert len(golden) == 107


def test_all_150_route_labels_parse():
    assert len(load_expected_routes(resolve(ROUTE_LABELS))) == 150


# --------------------------------------------------------------- ordering, and why it matters


def test_tickets_are_returned_in_arrival_order(tickets):
    """
    Asserts on *shuffled* input on purpose. The obvious version -- load the file, check the
    timestamps are ordered -- passes with the sort deleted, because the dataset file is already
    chronological. That is a test passing for the wrong reason.
    """
    import json
    import random

    stamps = [t.created_at for t in tickets]
    assert stamps == sorted(stamps)

    payload = json.loads(resolve(TICKETS).read_text(encoding="utf-8"))
    rows = payload["tickets"][:]
    random.Random(7).shuffle(rows)
    assert [r["ticket_id"] for r in rows] != [r["ticket_id"] for r in payload["tickets"]]

    shuffled = load_tickets_from_records(rows)
    assert [t.created_at for t in shuffled] == sorted(t.created_at for t in shuffled)
    assert [t.ticket_id for t in shuffled] == [t.ticket_id for t in tickets]


def test_every_timestamp_is_timezone_aware(tickets):
    """
    A naive datetime among aware ones makes the sort above raise `TypeError` -- three modules
    from where the offset went missing. The validator moves that failure to the record.
    """
    assert all(t.created_at.tzinfo is not None for t in tickets)


def test_the_four_escalating_threads_are_ordered_within_themselves(tickets):
    """
    The threads HLD §6 exists for. A customer's later ticket must never sort before an earlier
    one, or ticket 3 is scored before ticket 1 is recorded.
    """
    by_customer: dict[str, list] = {}
    for t in tickets:
        by_customer.setdefault(t.customer_id, []).append(t.created_at)
    multi = {c: s for c, s in by_customer.items() if len(s) > 1}
    assert multi, "expected at least one multi-ticket customer"
    for stamps in multi.values():
        assert stamps == sorted(stamps)


# ------------------------------------------------------- the vocabularies are a real contract


def test_constants_cover_every_label_in_the_data(tickets, golden):
    """If `Route` drifts from the label file, route accuracy silently measures nothing."""
    assert {t.category for t in tickets} <= set(CATEGORIES)
    assert {t.priority for t in tickets} <= set(PRIORITIES)
    assert {g.expected_route for g in golden.values()} <= set(ROUTES)
    assert {g.expected_sentiment for g in golden.values()} <= set(SENTIMENTS)
    assert {g.difficulty for g in golden.values()} <= set(DIFFICULTIES)


def test_golden_only_labels_the_two_reviewer_actions_we_can_simulate(golden):
    """Six actions supported, two labelled. No ground truth exists for "a human would edit"."""
    assert {g.expected_reviewer_action for g in golden.values()} == set(GOLDEN_REVIEWER_ACTIONS)


def test_difficulty_split_is_the_one_the_design_assumes(golden):
    """45 hard of 107. HLD §8.2 reports accuracy on this subset separately, so its size is load-bearing."""
    assert sum(1 for g in golden.values() if g.is_hard) == 45


def test_escalation_targets_are_valid_on_refuse(golden):
    """
    Route and escalation are orthogonal: some tickets are REFUSE *and* open an internal file.

    7 over all 150, but only 6 in the golden set -- TCK-1099 has no golden record. Pinned
    because the two label files have different coverage, and a metric that quietly picks the
    narrower one reports a denominator nobody expects. Route accuracy belongs on the 150;
    groundedness and citations can only be scored on the 107.
    """
    labels = load_expected_routes(resolve(ROUTE_LABELS))
    over_150 = [v for v in labels.values() if v.route == "REFUSE" and v.escalation_target]
    assert len(over_150) == 7

    over_107 = [
        g for g in golden.values() if g.expected_route == "REFUSE" and g.expected_escalation_target
    ]
    assert len(over_107) == 6

    # 52 ESCALATE but 59 targeted: the gap is exactly the seven above.
    assert sum(1 for v in labels.values() if v.escalation_target) == 59
    assert sum(1 for v in labels.values() if v.route == "ESCALATE") == 52


def test_the_eight_no_policy_tickets_are_flagged(golden):
    no_policy = [g for g in golden.values() if g.no_policy_in_kb]
    assert len(no_policy) == 8
    # All eight must escalate: correct behaviour is "say policy could not be verified, escalate".
    assert {g.expected_route for g in no_policy} == {"ESCALATE"}


# ----------------------------------------------------------------- strictness, both directions


def test_an_unknown_ticket_field_is_rejected(tickets):
    """A renamed field would otherwise parse cleanly and quietly break the ~38 fee tickets."""
    raw = tickets[0].model_dump(mode="json")
    raw["surprise_field"] = 1
    with pytest.raises(ValidationError):
        Ticket.model_validate(raw)


def test_customer_context_accepts_extras_on_purpose(tickets):
    """
    The deliberate exception: `account_age_days` is on 1 of 150 tickets. Forbidding extras here
    would reject a valid record; forbidding them on `Ticket` catches a renamed field.
    """
    raw = tickets[0].model_dump(mode="json")
    raw["customer_context"]["some_new_signal"] = 3
    assert Ticket.model_validate(raw).customer_context.model_extra["some_new_signal"] == 3


def test_a_bad_route_literal_is_rejected():
    from src.utils.schemas import GoldenRecord

    with pytest.raises(ValidationError):
        GoldenRecord.model_validate(
            {
                "ticket_id": "X",
                "subject": "s",
                "category": "disputes_and_fees",
                "difficulty": "easy",
                "expected_route": "ESCLATE",  # typo -- must not be accepted
                "expected_sentiment": "neutral",
                "expected_confidence_band": [0.5, 0.9],
                "expected_reviewer_action": "APPROVE",
                "priority": "low",
            }
        )


# ----------------------------------------------------- the system-role turns the schema found


def test_system_turns_exist_and_are_marked_internal(tickets):
    """
    6 turns across 4 tickets are internal events, not customer speech. Two are load-bearing:
    TCK-1044's denial letter is the re-opened-claim trigger, TCK-1101's geolocation mismatch is
    a fraud signal. Typed as `str`, both would have been silently mislabelled.
    """
    with_system = [t for t in tickets if t.system_events]
    assert len(with_system) == 4
    assert sum(len(t.system_events) for t in with_system) == 6
    assert all(turn.is_internal for t in with_system for turn in t.system_events)


def test_transcript_can_exclude_internal_turns(tickets):
    """"Source IP geolocation: inconsistent" in a reply is the disclosure DSP-006 prohibits."""
    t = next(t for t in tickets if t.system_events)
    assert "[system @" in t.transcript()
    assert "[system @" not in t.transcript(include_internal=False)


# ------------------------------------------------------------------ the precondition tri-state


def test_precondition_met_is_a_tri_state():
    """Collapsing `None` into `False` turns "we don't know" into "no" -- confidently wrong."""
    from src.utils.schemas import Precondition

    unknown = Precondition(name="fee_within_60_days", met=None, reason="fee date not structured")
    assert unknown.indeterminate
    assert not Precondition(name="x", met=False).indeterminate


def test_golden_files_are_valid_json():
    """A cheap guard: a truncated write would otherwise surface as a confusing schema error."""
    for path in (TICKETS, SAMPLE, GOLDEN, ROUTE_LABELS):
        json.loads(resolve(path).read_text(encoding="utf-8"))
