"""
Phoenix tracing. Off by default, lazily imported, and unable to fail a run.

The boundary is the point: **traces answer "what did it do and how long did it take"; the
evaluators in `src/evaluation/` answer "was it right".** Only the second needs the golden
labels, and an observability tool must never become the reason the evaluation does not exist --
so a missing, broken or unreachable Phoenix downgrades to a log line and the run continues.

    pip install arize-phoenix openinference-instrumentation-langchain
    phoenix serve                               # UI on localhost:6006

LangGraph runs on LangChain callbacks, so `auto_instrument=True` picks up every node, model call
and retrieval span with no per-node work. The surface stops there deliberately (HLD §11).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from src.utils.config import app_config

log = logging.getLogger(__name__)

# Registration is global to the process: OpenTelemetry installs one tracer provider, and calling
# `register` per ticket would rebuild it 150 times and duplicate every span.
_registered = False


def settings() -> dict[str, Any]:
    return app_config().get("observability", {}) or {}


def enabled() -> bool:
    return bool(settings().get("enabled", False))


def start_tracing(run_id: str) -> bool:
    """
    Register the tracer once per process. Returns whether tracing is actually on.

    The return value is not decoration: P8 asks you to report whether spans appeared, and a
    caller that assumes success prints "traced" over a run that was never traced.
    """
    global _registered
    if _registered:
        return True
    if not enabled():
        return False

    try:
        from phoenix.otel import register
    except ImportError as exc:
        log.warning("observability.enabled is true but Phoenix is not installed (%s); "
                    "the run continues untraced", exc)
        return False

    # A resource attribute rather than a per-span tag: one process runs one batch, so this puts
    # the run id on every span and lets a Phoenix trace be matched back to an audit record.
    os.environ["OTEL_RESOURCE_ATTRIBUTES"] = f"run.id={run_id}"

    options = settings()
    try:
        register(
            project_name=str(options.get("project_name", "support-ticket-agent")),
            endpoint=str(options.get("endpoint", "http://localhost:6006/v1/traces")),
            auto_instrument=True,
        )
    except Exception as exc:
        # Broad on purpose. A collector that is not listening raises from inside the OTel
        # exporter, and a run of 150 tickets must not die because nobody started Phoenix.
        log.warning("Phoenix registration failed (%s); the run continues untraced", exc)
        return False

    _registered = True
    log.info("Phoenix tracing on: project=%s run.id=%s", options.get("project_name"), run_id)
    return True
