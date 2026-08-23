"""
Case history (HLD §6). Three properties, each of which was a bug at some point today.

    python -m pytest tests/test_memory.py -v
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.memory.customer_thread_store import CustomerThreadStore
from src.utils.config import resolve
from src.utils.schemas import CaseSummary, load_tickets

TICKETS = "data/tickets/synthetic_tickets.json"


@pytest.fixture(scope="module")
def tickets():
    return load_tickets(resolve(TICKETS))


@pytest.fixture(autouse=True)
def isolate_store(tmp_path, monkeypatch):
    """The thread store is a process-wide singleton; tests must not inherit each other's."""
    from src.utils.config import app_config

    CustomerThreadStore.reset_default()
    monkeypatch.setitem(app_config()["outputs"], "customer_threads",
                        str(tmp_path / "threads.jsonl"))
    yield
    CustomerThreadStore.reset_default()


@pytest.fixture
def store(tmp_path):
    CustomerThreadStore.reset_default()
    return CustomerThreadStore(tmp_path / "threads.jsonl").load()


def test_history_accumulates_within_a_run(tickets, store):
    """A ticket must see what earlier tickets from the same customer produced in this run."""
    threads = {}
    for t in tickets:
        threads.setdefault(t.customer_id, []).append(t)
    customer, thread = max(threads.items(), key=lambda kv: len(kv[1]))
    assert len(thread) >= 3, "expected a multi-ticket thread in the dataset"

    seen = []
    for t in thread:
        seen.append(len(store.history_for(t)))
        store.append(
            customer,
            CaseSummary(
                ticket_id=t.ticket_id,
                subject=t.subject,
                created_at=t.created_at,
                disposition="escalated",
            ),
        )
    # Strictly non-decreasing, and the last ticket sees more than the first.
    assert seen == sorted(seen)
    assert seen[-1] > seen[0]


def test_sources_are_merged_by_field_not_by_row(tickets, store):
    """
    A prior ticket can arrive from two places, and each owns different fields:

    - **disposition** from the seed. Ours is a draft pending review, and feeding it back means
      one mistake on ticket 1 becomes three across the thread, each corroborated by the last.
    - **route / escalation_target** from our own row. The seed has neither, and "escalate to a
      different target than last time" needs to know the last target.
    """
    ticket = next(t for t in tickets if t.related_tickets)
    prior = ticket.related_tickets[0]
    store.append(
        ticket.customer_id,
        CaseSummary(
            ticket_id=prior.ticket_id,
            subject=prior.subject,
            created_at=prior.created_at,
            disposition="OUR-OWN-GUESS",
            route="ESCALATE",
            escalation_target="Fraud Investigations",
        ),
    )
    entry = {h.ticket_id: h for h in store.history_for(ticket)}[prior.ticket_id]

    assert entry.disposition == prior.disposition  # ground truth
    assert entry.disposition != "OUR-OWN-GUESS"
    assert entry.escalation_target == "Fraud Investigations"  # only we know this
    assert entry.route == "ESCALATE"


def test_a_ticket_never_reads_the_future(tickets, store):
    """
    Without the `created_at` filter a re-run lets ticket 1 decide using ticket 3's outcome.
    Every metric inflates, and nothing like it can happen in production.
    """
    ticket = next(t for t in tickets if t.related_tickets)
    store.append(
        ticket.customer_id,
        CaseSummary(
            ticket_id="TCK-FUTURE",
            subject="later",
            created_at=ticket.created_at + timedelta(days=1),
            disposition="escalated",
        ),
    )
    assert "TCK-FUTURE" not in {h.ticket_id for h in store.history_for(ticket)}


def test_history_is_ordered_oldest_first(tickets, store):
    ticket = max(tickets, key=lambda t: len(t.related_tickets))
    history = store.history_for(ticket)
    assert [h.created_at for h in history] == sorted(h.created_at for h in history)


# --------------------------------------------------------------- thread pressure (P6)


def test_pressure_rises_with_the_thread(tickets):
    """
    CUST-0022 is the four-ticket escalating story: a denied dispute, an account closure, a
    demand for the rep's name, then retained counsel and a CFPB filing.
    """
    from src.routing.thread_pressure import assess
    from src.utils.schemas import CaseSummary

    thread = sorted(
        (t for t in tickets if t.customer_id == "CUST-0022"), key=lambda t: t.created_at
    )
    assert len(thread) == 4

    history: list[CaseSummary] = []
    levels = []
    for ticket in thread:
        levels.append(assess(ticket, list(history)).level)
        history.append(
            CaseSummary(
                ticket_id=ticket.ticket_id, subject=ticket.subject,
                created_at=ticket.created_at, disposition="escalated", route="ESCALATE",
            )
        )
    assert levels == sorted(levels), "pressure must never fall as a thread continues"
    assert levels[0] == 0 and levels[-1] == 2


def test_a_prohibited_request_is_still_refused_under_pressure(tickets):
    """
    TCK-1109 has two prior escalations and asks for the rep's name and office. Pressure must
    not turn a refusal into an escalation -- a prohibited request stays prohibited however
    hard the thread is pushing.
    """
    from src.routing.rules_engine import compute, propose_route
    from src.safety.policy_checker import scan_ticket
    from src.utils.schemas import CaseSummary

    ticket = next(t for t in tickets if t.ticket_id == "TCK-1109")
    history = [
        CaseSummary(ticket_id=f"TCK-10{i}", subject="prior", created_at=ticket.created_at,
                    disposition="escalated", route="ESCALATE")
        for i in (44, 95)
    ]
    flags = scan_ticket(ticket)
    route, why = propose_route(ticket, compute(ticket, {}, history), flags)
    assert route == "REFUSE", why


def test_a_repeatedly_escalated_thread_gets_a_different_queue(tickets):
    """
    Sending TCK-1125 back to the queue that produced the denial it is complaining about is how
    a complaint becomes a regulatory filing.
    """
    from src.routing.thread_pressure import assess, escalation_target_for
    from src.utils.schemas import CaseSummary

    ticket = next(t for t in tickets if t.ticket_id == "TCK-1125")
    history = [
        CaseSummary(ticket_id=f"TCK-11{i}", subject="prior", created_at=ticket.created_at,
                    disposition="escalated", route="ESCALATE")
        for i in (44, 95, 9)
    ]
    assert escalation_target_for(assess(ticket, history), "Claims Specialist") == \
        "Executive Complaints"
    # A first contact keeps whatever the normal rules chose.
    assert escalation_target_for(assess(ticket, []), "Claims Specialist") == "Claims Specialist"


def test_history_loads_by_default_so_no_entry_point_can_forget_it(tickets):
    """
    Case history was wired into `main.py` and silently absent from `route_eval`, so the four
    threads got no benefit from it in any measurement. Loading is now the default.
    """
    from src.graph.graph_state import initial_state

    ticket = next(t for t in tickets if t.related_tickets)
    assert initial_state(ticket, run_id="t")["customer_history"]
    assert initial_state(ticket, run_id="t", customer_history=[])["customer_history"] == []
