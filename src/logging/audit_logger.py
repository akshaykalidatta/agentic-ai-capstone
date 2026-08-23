"""
The append-only decision record: one JSONL line per ticket per run.

The test of sufficiency is "could you defend this decision six months from now, without
re-running the agent?", so the record stores what the decision was made *from* -- every
retrieval attempt, each precondition with its inputs, both route proposals, the loop counters.

JSONL rather than a JSON array: a crash halfway through 150 tickets still leaves a readable
file, and `jq` can stream it.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from src.graph.graph_state import GraphState, loop_count
from src.utils.config import CONFIG_DIR, app_config, resolve
from src.utils.schemas import jsonable as _jsonable

log = logging.getLogger(__name__)


def config_hash() -> str:
    """
    Content hash of every config YAML. Comparing two runs' accuracy is meaningless if a
    threshold changed between them, and a version string only helps if someone bumps it.
    """
    digest = hashlib.sha256()
    for path in sorted(CONFIG_DIR.glob("*.yaml")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def build_record(state: GraphState) -> dict[str, Any]:
    """
    Flatten a finished state into one record, grouped by *when it was produced* rather than
    alphabetically, so reading it top to bottom replays the decision in order.
    """
    ticket = state.get("ticket")
    return {
        "run_id": state.get("run_id"),
        "ticket_id": state.get("ticket_id"),
        "logged_at": datetime.now().astimezone().isoformat(),
        "config_hash": config_hash(),
        "hitl_mode": state.get("hitl_mode"),
        "ticket": {
            "subject": getattr(ticket, "subject", None),
            "category": getattr(ticket, "category", None),
            "product_area": getattr(ticket, "product_area", None),
            "priority": getattr(ticket, "priority", None),
            "created_at": getattr(ticket, "created_at", None),
            "customer_id": getattr(ticket, "customer_id", None),
        },
        "customer_history": _jsonable(state.get("customer_history", [])),
        "sentiment": state.get("sentiment"),
        "safety_flags": _jsonable(state.get("safety_flags", [])),
        "intent": state.get("intent"),
        "entities": _jsonable(state.get("entities", {})),
        "preconditions": _jsonable(state.get("preconditions", {})),  # verdicts AND their inputs
        "retrieval_mode": state.get("retrieval_mode"),
        "retrieval_log": _jsonable(state.get("retrieval_log", [])),  # every attempt, not the last
        "retrieved": [
            {
                "chunk_id": chunk.chunk_id,
                "policy_id": chunk.policy_id,
                "source_file": chunk.source_file,
                "similarity": chunk.similarity,
                "injected": chunk.injected,
                "citable": chunk.citable,
            }
            for chunk in state.get("retrieved", []) or []
        ],
        "policy_analysis": _jsonable(state.get("policy_analysis")),
        "rule_route": state.get("rule_route"),
        "llm_route": state.get("llm_route"),
        "route": state.get("route"),
        "route_rationale": state.get("route_rationale"),
        "escalation_target": state.get("escalation_target"),
        "escalation_visible_to_customer": state.get("escalation_visible_to_customer"),
        "confidence": state.get("confidence"),
        "confidence_parts": _jsonable(state.get("confidence_parts", {})),
        "draft": state.get("draft"),
        "cited_policy_ids": state.get("cited_policy_ids", []),
        "validation": _jsonable(state.get("validation")),
        "loops": {name: loop_count(state, name) for name in
                  ("retrieval_refine", "confidence_recheck", "draft_repair")},
        "loops_capped": list(state.get("loops_capped", []) or []),
        "reviewer": _jsonable(state.get("reviewer")),
        "trace": _jsonable(state.get("trace", [])),
        "notes": list(state.get("notes", []) or []),
    }


class AuditLogger:
    """One per run. Opens the file lazily so a run that never reaches audit leaves nothing."""

    def __init__(self, run_id: str, directory: Path | str | None = None) -> None:
        base = (
            Path(directory)
            if directory
            else resolve(app_config()["paths"]["outputs"]) / "audit_logs"
        )
        self.run_id = run_id
        self.path = Path(base) / f"run_{run_id}.jsonl"
        self._directory_created = False

    def write(self, state: GraphState) -> dict[str, Any]:
        record = build_record(state)
        if not self._directory_created:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._directory_created = True
        # "a" is the entire append-only guarantee. Never "w".
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return record
