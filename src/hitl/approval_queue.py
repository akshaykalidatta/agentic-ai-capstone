"""
The append-only index of pending reviews.

Two sources answer "what is waiting for a human", and both are needed. The **checkpointer** is
the truth about whether a thread is suspended. This file makes the pending set *enumerable*
without scanning every thread id ever created.

It is never rewritten to mark something done: a completion is another line, and the pending set
is a fold over the whole file. An index you can rewrite is an index that can drift from the
checkpointer, and the checkpointer is the one that is right -- so when they disagree,
`review_service` shows the disagreement rather than picking a winner.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from dataclasses import fields as dataclass_fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.utils.config import app_config, resolve

QUEUED = "queued"
REVIEWED = "reviewed"


def default_queue_path() -> Path:
    return resolve(app_config()["outputs"]["approval_queue"])


@dataclass(frozen=True)
class QueueEntry:
    """
    One pending review, carrying enough to triage it without opening the checkpoint.

    Everything here is also in the interrupt payload; it is duplicated so the queue screen can
    sort 150 rows by confidence without deserialising 150 checkpoints.
    """

    run_id: str
    ticket_id: str
    subject: str = ""
    route: str | None = None
    confidence: float = 0.0
    escalation_target: str | None = None
    escalation_visible_to_customer: bool = True
    rule_route: str | None = None
    llm_route: str | None = None
    proposals_disagree: bool = False
    loops_capped: list[str] = field(default_factory=list)
    queued_at: str = ""

    @property
    def thread_id(self) -> str:
        """
        The format `main.py` already uses, reconstructed from the entry alone.

        That reconstruction is what makes a restart recoverable: nothing about resuming a review
        depends on an object that lived in the previous process.
        """
        return f"{self.run_id}:{self.ticket_id}"

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> QueueEntry:
        return cls(
            run_id=str(payload.get("run_id") or ""),
            ticket_id=str(payload.get("ticket_id") or ""),
            subject=str((payload.get("ticket") or {}).get("subject") or ""),
            route=payload.get("route"),
            confidence=float(payload.get("confidence") or 0.0),
            escalation_target=payload.get("escalation_target"),
            escalation_visible_to_customer=bool(
                payload.get("escalation_visible_to_customer", True)
            ),
            rule_route=payload.get("rule_route"),
            llm_route=payload.get("llm_route"),
            proposals_disagree=bool(payload.get("proposals_disagree")),
            loops_capped=list(payload.get("loops_capped") or []),
            queued_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_record(self) -> dict[str, Any]:
        return {"event": QUEUED, **asdict(self)}

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> QueueEntry:
        # Unknown keys are dropped rather than raising: the file is append-only and outlives any
        # one shape of this dataclass, so a queue written last week must still fold today.
        known = {f.name for f in dataclass_fields(cls)}
        return cls(**{key: value for key, value in record.items() if key in known})


def fold_pending(records: Iterable[dict[str, Any]]) -> list[QueueEntry]:
    """
    Replay the file in order; the last event for a ticket decides whether it is still pending.

    A ticket reviewed twice -- sent back for regeneration, then approved -- writes
    queued, reviewed, queued, reviewed and folds to nothing. Counting `queued` lines would
    leave it pending forever.
    """
    pending: dict[str, QueueEntry] = {}
    for record in records:
        key = f"{record.get('run_id')}:{record.get('ticket_id')}"
        if record.get("event") == QUEUED:
            pending[key] = QueueEntry.from_record(record)
        elif record.get("event") == REVIEWED:
            pending.pop(key, None)
    return list(pending.values())


class ApprovalQueue:
    """Append-only JSONL. The only two writes are one `queued` line and one `reviewed` line."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else default_queue_path()

    def _append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # "a" is the whole guarantee. Never "w".
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def append_queued(self, entry: QueueEntry) -> None:
        self._append(entry.to_record())

    def append_reviewed(self, run_id: str, ticket_id: str, action: str) -> None:
        self._append(
            {
                "event": REVIEWED,
                "run_id": run_id,
                "ticket_id": ticket_id,
                "action": action,
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def records(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def pending(self) -> list[QueueEntry]:
        return fold_pending(self.records())
