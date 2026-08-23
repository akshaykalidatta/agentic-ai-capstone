"""
Per-node timing, added by a decorator so no node has to remember to do it.

A node returns `{"sentiment": ..., "_summary": "neutral, no flags"}` and the decorator turns
the `_summary` into a `NodeTrace`. Leading underscore means "message to my wrapper, not part
of the state".
"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from src.utils.schemas import NodeTrace

log = logging.getLogger(__name__)

NodeFunction = Callable[[dict[str, Any]], dict[str, Any]]

# LangGraph signals suspension by raising: `hitl_gate` calling `interrupt()` in interactive mode
# comes out of the node body as an exception that is control flow, not failure. Matched by class
# name up the MRO so this module stays importable with no langgraph installed, which is what
# lets `tests/test_graph_topology.py` run on a bare checkout.
CONTROL_FLOW_EXCEPTIONS = frozenset({"GraphInterrupt", "GraphBubbleUp", "ParentCommand"})


def _is_control_flow(exc: BaseException) -> bool:
    return any(base.__name__ in CONTROL_FLOW_EXCEPTIONS for base in type(exc).__mro__)


def traced(node_name: str) -> Callable[[NodeFunction], NodeFunction]:
    def decorator(node_function: NodeFunction) -> NodeFunction:
        # functools.wraps: without it all twelve wrappers are named "wrapper", and every
        # traceback and log line becomes unreadable at once.
        @functools.wraps(node_function)
        def wrapper(state: dict[str, Any]) -> dict[str, Any]:
            started_at = datetime.now(timezone.utc)
            start = time.perf_counter()
            ticket_id = state.get("ticket_id", "?")
            try:
                update = node_function(state) or {}
            except Exception as exc:
                # A suspended node has not failed, and logging a traceback for every interactive
                # review would train the reader to ignore this log.
                if _is_control_flow(exc):
                    raise
                # No trace is written: LangGraph discards a failed node's update entirely, so
                # there is nothing to attach one to. Swallowing the error would be worse -- a
                # node returning {} on failure routes the ticket on empty analysis.
                log.exception("node %s failed on %s", node_name, ticket_id)
                raise

            elapsed_ms = (time.perf_counter() - start) * 1000
            if "trace" in update:
                raise RuntimeError(f"node {node_name!r} must not write 'trace' directly")

            summary = str(update.pop("_summary", ""))
            update["trace"] = [
                NodeTrace(
                    node=node_name,
                    started_at=started_at,
                    ms=round(elapsed_ms, 2),
                    summary=summary,
                )
            ]
            log.debug("%s | %-16s %6.1f ms | %s", ticket_id, node_name, elapsed_ms, summary)
            return update

        return wrapper

    return decorator


def format_trace(traces: list[NodeTrace]) -> str:
    """One line per node, for verbose runs."""
    if not traces:
        return "(no nodes ran)"
    width = max(len(entry.node) for entry in traces)
    lines = [f"  {e.node:<{width}}  {e.ms:7.1f} ms  {e.summary}" for e in traces]
    lines.append(f"  {'total':<{width}}  {sum(e.ms for e in traces):7.1f} ms")
    return "\n".join(lines)
