"""
Case history: what earlier tickets from the same customer contribute to this one.

Four customers appear as one escalating story -- a denied dispute becoming a complaint about
staff becoming a regulatory threat. Read the third ticket alone and it looks mildly annoyed;
read it after the first two and it should escalate faster, and to a different target.

Seeded from each ticket's `related_tickets` and appended to after every decision, so a ticket
sees both what happened before the run and what happened during it. That is also why the run
must be ordered and single-threaded.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.utils.config import app_config, resolve
from src.utils.schemas import CaseSummary, Ticket

log = logging.getLogger(__name__)


class CustomerThreadStore:
    """In-memory index (the read path) over an append-only JSONL file (durability + audit)."""

    _default_instance: CustomerThreadStore | None = None

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = (
            Path(path)
            if path
            else resolve(app_config()["outputs"].get("customer_threads",
                                                     "outputs/customer_threads.jsonl"))
        )
        self._summaries_by_customer: dict[str, list[CaseSummary]] = {}
        self._loaded = False

    @classmethod
    def default(cls) -> CustomerThreadStore:
        """
        Process-wide singleton. Shared mutable state across the run *is* the feature here:
        ticket 3 must see what ticket 1 wrote.
        """
        if cls._default_instance is None:
            cls._default_instance = cls()
            cls._default_instance.load()
        return cls._default_instance

    @classmethod
    def reset_default(cls) -> None:
        """Tests need this; nothing else should call it."""
        cls._default_instance = None

    def load(self) -> CustomerThreadStore:
        self._summaries_by_customer.clear()
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    summary = CaseSummary.model_validate(row["summary"])
                    self._summaries_by_customer.setdefault(row["customer_id"], []).append(summary)
        self._loaded = True
        return self

    def history_for(self, ticket: Ticket) -> list[CaseSummary]:
        """
        Everything known about this customer *before* this ticket, oldest first.

        The `created_at` filter stops a re-run reading back rows this same store wrote for
        later tickets in the thread -- which would let ticket 1 decide using ticket 3's outcome
        and inflate every metric.
        """
        if not self._loaded:
            self.load()

        seeded = [
            CaseSummary(
                ticket_id=related.ticket_id,
                subject=related.subject,
                created_at=related.created_at,
                disposition=related.disposition,
            )
            for related in ticket.related_tickets
        ]
        observed = [
            summary
            for summary in self._summaries_by_customer.get(ticket.customer_id, [])
            if summary.created_at < ticket.created_at and summary.ticket_id != ticket.ticket_id
        ]

        # When a prior ticket appears in both sources, merge by FIELD, not by row:
        #   disposition  <- the seed. Ours is a draft pending review, and feeding the agent its
        #                   own earlier output compounds one mistake across a whole thread.
        #   route/target <- the observed row. The seed has neither, and "escalate to a
        #                   different target than last time" needs to know the last target.
        merged: dict[str, CaseSummary] = {s.ticket_id: s for s in observed}
        for seed in seeded:
            previous = merged.get(seed.ticket_id)
            merged[seed.ticket_id] = (
                seed
                if previous is None
                else seed.model_copy(
                    update={
                        "route": previous.route,
                        "escalation_target": previous.escalation_target,
                    }
                )
            )
        return sorted(merged.values(), key=lambda summary: summary.created_at)

    def append(self, customer_id: str, summary: CaseSummary) -> None:
        self._summaries_by_customer.setdefault(customer_id, []).append(summary)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {"customer_id": customer_id, "summary": summary.model_dump(mode="json")},
                    ensure_ascii=False,
                )
                + "\n"
            )

    def append_from_state(self, state: dict[str, Any]) -> CaseSummary | None:
        """Called by `audit_log` once the decision is final."""
        ticket = state.get("ticket")
        if ticket is None:
            return None
        route = state.get("route")
        summary = CaseSummary(
            ticket_id=ticket.ticket_id,
            subject=ticket.subject,
            created_at=ticket.created_at,
            disposition=_disposition_for(route, state.get("reviewer")),
            route=route,
            escalation_target=state.get("escalation_target"),
        )
        self.append(ticket.customer_id, summary)
        return summary


def _disposition_for(route: str | None, reviewer: Any) -> str:
    """A fact a later ticket can act on, without inheriting this run's reasoning."""
    if getattr(reviewer, "action", None) == "REJECT":
        return "rejected at review"
    return {
        "AUTO_RESOLVE": "resolved",
        "ESCALATE": "escalated",
        "REFUSE": "declined",
        "ASK_MORE_INFO": "awaiting customer information",
    }.get(route or "", "unknown")
