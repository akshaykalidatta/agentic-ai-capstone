"""
Assembly. Two ways to run the same topology tables.

- `build_graph()` compiles a real LangGraph. This is what `main.py` uses.
- `walk_graph()` executes the same `NODES` / `EDGES` / `CONDITIONAL_EDGES` in plain Python,
  with no langgraph import, so `tests/test_graph_topology.py` can prove the loops terminate on
  a bare checkout. It is a harness, not a second implementation -- if the two ever disagree
  about an outcome, `build_graph()` is right.
"""

from __future__ import annotations

import logging
import operator
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from src.graph.edges import CONDITIONAL_EDGES, EDGES, ROUTERS
from src.graph.graph_state import GraphState
from src.graph.nodes import NODES
from src.utils.config import app_config, resolve

log = logging.getLogger(__name__)

START = "__start__"
END = "__end__"


def build_graph(*, checkpointer: Any | None = None, uncompiled: bool = False) -> Any:
    """
    Wire and compile the LangGraph. Imports are inside the function so this module stays
    importable without langgraph.

    The checkpointer is what lets P7 suspend the graph inside `hitl_gate` via `interrupt()`
    and resume after the reviewer acts.
    """
    from langgraph.graph import END as LANGGRAPH_END
    from langgraph.graph import START as LANGGRAPH_START
    from langgraph.graph import StateGraph

    sentinels = {START: LANGGRAPH_START, END: LANGGRAPH_END}
    builder = StateGraph(GraphState)

    for name, node_function in NODES.items():
        builder.add_node(name, node_function)
    for source, destination in EDGES:
        builder.add_edge(sentinels.get(source, source), sentinels.get(destination, destination))
    for source, mapping in CONDITIONAL_EDGES.items():
        builder.add_conditional_edges(source, ROUTERS[source], dict(mapping))

    if uncompiled:
        return builder
    return builder.compile(checkpointer=checkpointer or _default_checkpointer())


def _default_checkpointer() -> Any | None:
    kind = str(app_config().get("graph", {}).get("checkpointer", "memory")).lower()
    if kind == "none":
        return None
    if kind == "sqlite":
        # Separate package (langgraph-checkpoint-sqlite), needed from P7 for durable review.
        # Every decision about *how* to build one -- connection ownership, thread affinity, the
        # metadata serializer -- lives in `checkpointing.py`, which `tests/test_hitl.py` uses
        # too, so the app and the gate cannot disagree about what a durable checkpointer is.
        from src.graph.checkpointing import sqlite_saver

        return sqlite_saver(
            resolve(app_config()["graph"].get("sqlite_path", "outputs/checkpoints.sqlite"))
        )
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()


def draw_mermaid() -> str:
    """LangGraph's renderer when available, the table renderer otherwise. Never hand-drawn."""
    try:
        return build_graph(checkpointer=None).get_graph().draw_mermaid()
    except ImportError:
        log.info("langgraph not installed; rendering from the topology tables")

    lines = ["flowchart TD", f"    {START}([START])", f"    {END}([END])"]
    lines += [f"    {name}[{name}]" for name in NODES]
    lines += [f"    {source} --> {destination}" for source, destination in EDGES]
    lines += [
        f"    {source} -.->|{key}| {destination}"
        for source, mapping in CONDITIONAL_EDGES.items()
        for key, destination in mapping.items()
    ]
    return "\n".join(lines)


def _additive_state_keys() -> set[str]:
    """
    Which `GraphState` keys use an `operator.add` reducer, read off the class annotations so a
    new reducer key cannot be forgotten. `include_extras=True` is required -- without it,
    `get_type_hints` strips the `Annotated` metadata and every key looks like an overwrite.
    """
    return {
        name
        for name, hint in get_type_hints(GraphState, include_extras=True).items()
        if get_origin(hint) is Annotated and operator.add in get_args(hint)[1:]
    }


def merge_state_update(state: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Apply one node's partial update: concatenate additive keys, overwrite the rest."""
    additive = _additive_state_keys()
    merged = dict(state)
    for key, value in update.items():
        if key in additive:
            merged[key] = list(merged.get(key) or []) + list(value or [])
        else:
            merged[key] = value
    return merged


class StepLimitExceeded(RuntimeError):
    """LangGraph's `GraphRecursionError` equivalent. If you see it, a router is wrong."""


def walk_graph(
    state: dict[str, Any], *, max_steps: int | None = None, trace_path: bool = False
) -> Any:
    """Execute the graph in plain Python. Returns the final state, or `(state, path)`."""
    limit = max_steps or int(app_config().get("graph", {}).get("recursion_limit", 40))
    plain_edges = dict(EDGES)
    current_node = plain_edges[START]
    path: list[str] = []

    for _ in range(limit):
        path.append(current_node)
        state = merge_state_update(state, NODES[current_node](state) or {})

        if current_node in CONDITIONAL_EDGES:
            key = ROUTERS[current_node](state)
            mapping = CONDITIONAL_EDGES[current_node]
            if key not in mapping:
                raise KeyError(
                    f"router for {current_node!r} returned {key!r}, not one of {sorted(mapping)}"
                )
            current_node = mapping[key]
        else:
            current_node = plain_edges[current_node]

        if current_node == END:
            return (state, path) if trace_path else state

    raise StepLimitExceeded(f"exceeded {limit} steps; path was {' -> '.join(path)}")
