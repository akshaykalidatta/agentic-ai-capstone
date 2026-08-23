"""
Entry point. `python -m src.main --help`.

    python -m src.main --gate                       P0's gate, then exit
    python -m src.main --sample                     the 13-ticket dev batch
    python -m src.main --all                        all 150, in arrival order
    python -m src.main --ticket TCK-1143 -v         one ticket with a per-node trace
    python -m src.main --sample --stub-retrieval    no index, no torch
    python -m src.main --sample --hitl interactive  queue the batch for a human
                                                    (then: streamlit run app/streamlit_app.py)
    python -m src.main --draw                       the generated mermaid diagram

The route distribution this prints is a property of the **stubs**, not a quality signal. What
a run does prove is that every ticket reaches `audit_log`, every router had a destination, no
loop ran away, and the audit record is complete.
"""

from __future__ import annotations

import argparse
import collections
import logging
import sys
from typing import Any

from src.graph.graph_state import initial_state, new_run_id, summarise
from src.logging.trace_logger import format_trace
from src.utils.config import app_config, resolve
from src.utils.constants import HITL_MODES, ROUTES
from src.utils.schemas import Ticket, load_expected_routes, load_golden, load_tickets

TICKETS_PATH = "data/tickets/synthetic_tickets.json"
SAMPLE_PATH = "data/tickets/sample_ticket_batch.json"
ROUTE_LABELS_PATH = "data/evaluation/expected_routes.json"


class StubRetriever:
    """
    Returns nothing, and you have to ask for it. Never a silent fallback -- a null retriever
    that engaged automatically when the index is missing would produce numbers that look like
    retrieval and are not. `mode` lands in every audit record, so a stubbed run self-labels.
    """

    mode = "stubbed"

    class EmptyResult:
        hits: list[Any] = []
        top_similarity = 0.0
        below_floor = True
        scope_signal = False

        def policy_ids(self, **_: Any) -> list[str]:
            return []

        def source_files(self) -> list[str]:
            return []

        def context_block(self, **_: Any) -> str:
            return ""

    def retrieve(self, query: str, **_: Any) -> Any:
        return self.EmptyResult()


def run_one_ticket(
    ticket: Ticket,
    *,
    run_id: str,
    golden: Any = None,
    hitl_mode: str = "auto",
    use_python_walker: bool = False,
    compiled_graph: Any = None,
    no_model: bool = False,
    review_service: Any = None,
) -> dict[str, Any]:
    state = initial_state(
        ticket,
        run_id=run_id,
        golden=golden,
        hitl_mode=hitl_mode,
        no_model=no_model,
    )

    if use_python_walker:
        from src.graph.support_graph import walk_graph

        return walk_graph(dict(state))

    # Interactive tickets suspend at `hitl_gate` instead of finishing, and the service is what
    # indexes them so a person can find them again.
    if review_service is not None:
        return review_service.start(dict(state))

    # thread_id namespaces the checkpointer. One per ticket, so P7 resumes the right review.
    config = {
        "configurable": {"thread_id": f"{run_id}:{ticket.ticket_id}"},
        "recursion_limit": int(app_config().get("graph", {}).get("recursion_limit", 40)),
    }
    return compiled_graph.invoke(state, config=config)


def run_batch(tickets: list[Ticket], args: argparse.Namespace) -> list[dict[str, Any]]:
    run_id = new_run_id()
    golden_records = (
        load_golden(resolve(app_config()["paths"]["golden_dataset"]))
        if args.hitl == "simulate"
        else {}
    )

    from src.graph import nodes

    if args.stub_retrieval:
        nodes.set_retriever(StubRetriever())
    elif args.engine:
        from src.retrieval.retriever import build_default_retriever

        nodes.set_retriever(build_default_retriever(engine=args.engine))

    # Interactive review owns its own compiled graph, because it also owns the sqlite
    # checkpointer connection the suspended threads live in.
    review_service = None
    if args.hitl == "interactive" and not args.walk:
        from src.hitl.review_service import ReviewService

        review_service = ReviewService()

    compiled_graph = None
    if not args.walk and review_service is None:
        from src.graph.support_graph import build_graph

        compiled_graph = build_graph()

    from src.utils.tracing import start_tracing

    traced_run = start_tracing(run_id)

    engine = "walk" if args.walk else "langgraph"
    notes = " | retrieval=STUBBED" if args.stub_retrieval else ""
    if args.no_model:
        notes += " | NO MODEL (deterministic only)"
    if traced_run:
        notes += " | tracing=phoenix"
    print(f"run {run_id} | {len(tickets)} tickets | hitl={args.hitl} | engine={engine}{notes}")
    print("-" * 78)

    results: list[dict[str, Any]] = []
    for position, ticket in enumerate(tickets, 1):
        try:
            state = run_one_ticket(
                ticket,
                run_id=run_id,
                golden=golden_records.get(ticket.ticket_id),
                hitl_mode=args.hitl,
                use_python_walker=args.walk,
                compiled_graph=compiled_graph,
                no_model=args.no_model,
                review_service=review_service,
            )
        except Exception as exc:
            logging.getLogger(__name__).exception("%s failed", ticket.ticket_id)
            if app_config().get("run", {}).get("stop_on_error", False):
                raise
            print(f"{position:>4}  {ticket.ticket_id}  ERROR  {type(exc).__name__}: {exc}")
            continue

        summary = summarise(state)
        results.append(summary)
        capped = summary["loops_capped"]
        # A ticket that never reached `audit_log` did not finish: it is suspended at the review
        # gate, waiting in outputs/approval_queue.jsonl. `finished_at` is the reliable signal --
        # `__interrupt__` on the returned state is not present in every langgraph version.
        tail = (
            "  AWAITING REVIEW"
            if state.get("finished_at") is None
            else f"{len(summary['nodes_run']):>2} nodes"
        )
        print(
            f"{position:>4}  {ticket.ticket_id}  {str(summary['route']):<14}"
            f"conf={summary['confidence']:.2f}  "
            f"{(summary['escalation_target'] or '-'):<28}"
            f"{tail}"
            + (f"  CAPPED:{','.join(capped)}" if capped else "")
        )
        if args.verbose:
            print(format_trace(state.get("trace", [])))
    return results


def print_report(results: list[dict[str, Any]]) -> None:
    print("-" * 78)
    routes = collections.Counter(result["route"] for result in results)
    print(f"{len(results)} tickets completed")
    print("routes (STUB-driven, not a quality signal):")
    for route in ROUTES:
        print(f"    {route:<16}{routes.get(route, 0):>4}")

    capped = collections.Counter(loop for r in results for loop in r["loops_capped"])
    modes = collections.Counter(result["retrieval_mode"] for result in results)
    nodes = collections.Counter(node for r in results for node in r["nodes_run"])
    print(f"loops capped: {dict(capped) or 'none'}")
    print(f"retrieval modes: {dict(modes)}")
    print(f"node executions: {dict(sorted(nodes.items()))}")


def run_gate() -> int:
    """
    P0's gate: all 150 tickets parse, plus the structural checks that the phase's real
    deliverable is a sound topology. Returns a process exit code so CI can use it.
    """
    from src.graph.edges import CONDITIONAL_EDGES, EDGES, LOOPS, ROUTERS
    from src.graph.nodes import NODES
    from src.utils.constants import NODE_NAMES

    paths = app_config()["paths"]
    reachable = {d for _, d in EDGES} | {d for m in CONDITIONAL_EDGES.values() for d in m.values()}
    bad_destinations = {
        source: sorted(set(mapping.values()) - set(NODES) - {"__end__"})
        for source, mapping in CONDITIONAL_EDGES.items()
        if set(mapping.values()) - set(NODES) - {"__end__"}
    }

    checks: list[tuple[str, bool, Any]] = [
        ("150 tickets parse", None, len(load_tickets(resolve(paths["tickets"])))),
        ("107 golden records parse", None, len(load_golden(resolve(paths["golden_dataset"])))),
        ("150 route labels parse", None, len(load_expected_routes(resolve(ROUTE_LABELS_PATH)))),
        ("node registry matches NODE_NAMES", set(NODES) == set(NODE_NAMES), ""),
        ("every node reachable", not (set(NODES) - reachable), set(NODES) - reachable or "yes"),
        ("every router destination exists", not bad_destinations, bad_destinations or "yes"),
        ("routers and conditional edges paired", set(ROUTERS) == set(CONDITIONAL_EDGES), ""),
    ]
    expected_counts = {"150 tickets parse": 150, "107 golden records parse": 107,
                       "150 route labels parse": 150}

    failures: list[str] = []
    for label, passed, detail in checks:
        if passed is None:
            passed = detail == expected_counts[label]
        print(f"[{'PASS' if passed else 'FAIL'}] {label}{f': {detail}' if detail != '' else ''}")
        if not passed:
            failures.append(label)

    for loop in LOOPS:
        exits = CONDITIONAL_EDGES[loop["router"]]
        passed = exits.get(loop["exit_key"]) == loop["exit_node"]
        print(f"[{'PASS' if passed else 'FAIL'}] loop {loop['name']} exits to {loop['exit_node']}")
        if not passed:
            failures.append(f"loop {loop['name']}")

    # ---- P1 retrieval. BM25 needs no index, so this is always runnable; dense/hybrid need
    # `python scripts/build_index.py` first and are reported as skipped without it.
    from src.evaluation.retrieval_eval import DOC_RECALL_GATE, evaluate as evaluate_retrieval
    from src.retrieval.retriever import build_default_retriever

    for engine in ("bm25", "hybrid"):
        try:
            report = evaluate_retrieval(build_default_retriever(engine=engine))
        except Exception as exc:
            print(f"[SKIP] P1 retrieval ({engine}): {type(exc).__name__}")
            continue
        passed = report.doc_recall >= DOC_RECALL_GATE
        print(f"[{'PASS' if passed else 'FAIL'}] P1 doc recall@5 ({engine}): "
              f"{report.doc_recall:.3f} (gate {DOC_RECALL_GATE:.2f})")
        if not passed and engine == "hybrid":
            failures.append(f"P1 recall ({engine})")

    # ---- P2 safety. Deterministic layer only, so it needs no model.
    from src.safety.policy_checker import scan_ticket

    by_id = {t.ticket_id: t for t in load_tickets(resolve(paths["tickets"]))}
    critical = ("TCK-1019", "TCK-1083")
    tone_traps = ("TCK-1077", "TCK-1084", "TCK-1149", "TCK-1018", "TCK-1104", "TCK-1125")
    flagged = sum(1 for t in critical if scan_ticket(by_id[t]))
    clean = sum(1 for t in tone_traps if not scan_ticket(by_id[t]))
    print(f"[{'PASS' if flagged == len(critical) else 'FAIL'}] P2 safety-critical flagged: "
          f"{flagged}/{len(critical)}")
    print(f"[{'PASS' if clean == len(tone_traps) else 'FAIL'}] P2 tone traps not flagged: "
          f"{clean}/{len(tone_traps)}")
    if flagged != len(critical):
        failures.append("P2 safety-critical")
    if clean != len(tone_traps):
        failures.append("P2 tone traps")

    print("-" * 78)
    if failures:
        print(f"GATE RED: {failures}")
        return 1
    print("GATE GREEN: topology, retrieval and safety gates all pass.")
    print("P3-P5 route accuracy needs a model: python -m src.evaluation.route_eval")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.main")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--all", action="store_true", help="all 150 tickets, arrival order")
    source.add_argument("--sample", action="store_true", help="the 13-ticket dev batch")
    source.add_argument("--ticket", metavar="ID", help="one ticket by id")
    parser.add_argument("--limit", type=int, help="first N tickets after ordering")
    parser.add_argument("--hitl", choices=HITL_MODES, help="review mode")
    parser.add_argument("--stub-retrieval", action="store_true", help="no index, no torch")
    parser.add_argument("--walk", action="store_true", help="python walker, no langgraph")
    parser.add_argument(
        "--no-model", action="store_true",
        help="deterministic layers only: patterns, rule engine, retrieval. No API key needed, "
             "and every route it produces is one the rules could defend on their own.",
    )
    parser.add_argument(
        "--engine", choices=("hybrid", "dense", "bm25"), default=None,
        help="retrieval backend; bm25 needs no index and no torch",
    )
    parser.add_argument("--draw", action="store_true", help="print the mermaid diagram and exit")
    parser.add_argument("--gate", action="store_true", help="run P0's gate and exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="per-node trace")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level="DEBUG" if args.verbose else app_config().get("logging", {}).get("level", "INFO"),
        format="%(levelname)-7s %(name)s | %(message)s",
    )

    if args.gate:
        return run_gate()
    if args.draw:
        from src.graph.support_graph import draw_mermaid

        print(draw_mermaid())
        return 0

    if args.hitl is None:
        args.hitl = app_config().get("hitl", {}).get("mode", "auto")
    if args.hitl == "interactive" and args.walk:
        # The walker has no checkpointer, so `interrupt()` has nothing to suspend into. Failing
        # here beats a LangGraph error raised twelve nodes deep.
        parser.error("--hitl interactive needs the real graph; drop --walk")

    tickets = load_tickets(resolve(SAMPLE_PATH if args.sample else TICKETS_PATH))
    if args.ticket:
        tickets = [t for t in tickets if t.ticket_id == args.ticket]
        if not tickets:
            parser.error(f"no ticket {args.ticket!r}")
    elif not (args.all or args.sample):
        parser.error("pick one of --all, --sample, --ticket, --draw or --gate")
    if args.limit:
        tickets = tickets[: args.limit]

    results = run_batch(tickets, args)
    print_report(results)
    return 0 if len(results) == len(tickets) else 1


if __name__ == "__main__":
    sys.exit(main())
