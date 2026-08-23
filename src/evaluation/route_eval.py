"""
Route accuracy, and the two critical error classes.

    python -m src.evaluation.route_eval --no-model --engine bm25   # deterministic floor
    python -m src.evaluation.route_eval                            # the real pipeline

Reported in the order HLD §8.2 asks for: **critical errors first, hard subset second,
aggregate last.** The aggregate inflates on the 65 easy tickets and says very little about the
design, so putting it at the top is how a project talks itself into believing it is finished.

The two critical error classes are tracked separately because their real-world cost is not
comparable to an ordinary miss:

- **Wrongly refused** -- REFUSE where the label was AUTO_RESOLVE or ESCALATE. A real customer
  denied service.
- **Wrongly auto-resolved** -- AUTO_RESOLVE where the label was ESCALATE on a safety or fraud
  ticket. An account takeover or a crisis disclosure handled by a bot.

Target for both: zero.
"""

from __future__ import annotations

import argparse
import collections
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.utils.config import app_config, resolve
from src.utils.constants import ROUTES

log = logging.getLogger(__name__)

OVERALL_GATE = 0.70
HARD_GATE = 0.55

# Categories where auto-resolving something that should have escalated is a critical error
# rather than an ordinary miss.
SAFETY_SENSITIVE = {"conduct_and_prohibited", "disputes_and_fees"}


@dataclass
class CaseResult:
    ticket_id: str
    expected: str
    predicted: str | None
    difficulty: str
    category: str
    expected_target: str | None
    predicted_target: str | None
    rule_route: str | None
    llm_route: str | None
    confidence: float
    rationale: str

    @property
    def correct(self) -> bool:
        return self.predicted == self.expected

    @property
    def target_correct(self) -> bool | None:
        """None when no target was expected -- scoring those as wrong would punish 91 tickets."""
        if not self.expected_target:
            return None
        return self.predicted_target == self.expected_target

    @property
    def wrongly_refused(self) -> bool:
        return self.predicted == "REFUSE" and self.expected in {"AUTO_RESOLVE", "ESCALATE"}

    @property
    def wrongly_auto_resolved(self) -> bool:
        return (
            self.predicted == "AUTO_RESOLVE"
            and self.expected == "ESCALATE"
            and self.category in SAFETY_SENSITIVE
        )


@dataclass
class RouteReport:
    n: int
    overall: float
    hard: float
    moderate: float
    easy: float
    wrongly_refused: list[str] = field(default_factory=list)
    wrongly_auto_resolved: list[str] = field(default_factory=list)
    per_route: dict[str, dict[str, float]] = field(default_factory=dict)
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    target_accuracy: float = 0.0
    rule_fired_rate: float = 0.0
    rule_precision: float = 0.0
    disagreement_rate: float = 0.0
    cases: list[dict[str, Any]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.overall >= OVERALL_GATE
            and self.hard >= HARD_GATE
            and not self.wrongly_refused
            and not self.wrongly_auto_resolved
        )


def _rate(hits: int, total: int) -> float:
    return round(hits / total, 4) if total else 0.0


def score(results: list[CaseResult]) -> RouteReport:
    by_difficulty = collections.defaultdict(list)
    for result in results:
        by_difficulty[result.difficulty].append(result)

    confusion: dict[str, dict[str, int]] = {
        expected: dict.fromkeys([*ROUTES, "none"], 0) for expected in ROUTES
    }
    for result in results:
        confusion[result.expected][result.predicted or "none"] += 1

    per_route: dict[str, dict[str, float]] = {}
    for route in ROUTES:
        predicted = [r for r in results if r.predicted == route]
        actual = [r for r in results if r.expected == route]
        true_positive = sum(1 for r in actual if r.correct)
        per_route[route] = {
            "support": len(actual),
            "precision": _rate(true_positive, len(predicted)),
            "recall": _rate(true_positive, len(actual)),
        }

    targeted = [r for r in results if r.target_correct is not None]
    rule_fired = [r for r in results if r.rule_route is not None]
    both = [r for r in results if r.rule_route and r.llm_route]

    return RouteReport(
        n=len(results),
        overall=_rate(sum(r.correct for r in results), len(results)),
        hard=_rate(
            sum(r.correct for r in by_difficulty["hard"]), len(by_difficulty["hard"])
        ),
        moderate=_rate(
            sum(r.correct for r in by_difficulty["moderate"]), len(by_difficulty["moderate"])
        ),
        easy=_rate(sum(r.correct for r in by_difficulty["easy"]), len(by_difficulty["easy"])),
        wrongly_refused=[r.ticket_id for r in results if r.wrongly_refused],
        wrongly_auto_resolved=[r.ticket_id for r in results if r.wrongly_auto_resolved],
        per_route=per_route,
        confusion=confusion,
        target_accuracy=_rate(sum(1 for r in targeted if r.target_correct), len(targeted)),
        rule_fired_rate=_rate(len(rule_fired), len(results)),
        rule_precision=_rate(sum(r.correct for r in rule_fired), len(rule_fired)),
        disagreement_rate=_rate(sum(1 for r in both if r.rule_route != r.llm_route), len(both)),
        cases=[asdict(r) for r in results],
    )


def print_report(report: RouteReport, *, label: str = "") -> None:
    print(f"\n=== route accuracy {label} ===")
    print(f"  tickets scored             {report.n}")

    # Critical errors first. Their cost is not comparable to an ordinary miss.
    print(f"\n  CRITICAL -- wrongly refused        {len(report.wrongly_refused)}  "
          f"{report.wrongly_refused[:6] or ''}")
    print(f"  CRITICAL -- wrongly auto-resolved  {len(report.wrongly_auto_resolved)}  "
          f"{report.wrongly_auto_resolved[:6] or ''}")

    print(f"\n  hard subset                {report.hard:.3f}   (gate {HARD_GATE:.2f})")
    print(f"  moderate                   {report.moderate:.3f}")
    print(f"  easy                       {report.easy:.3f}")
    print(f"  escalation target accuracy {report.target_accuracy:.3f}")

    print("\n  per route      support  precision  recall")
    for route, stats in report.per_route.items():
        print(f"    {route:<14}{stats['support']:>5}   {stats['precision']:>8.3f}"
              f"  {stats['recall']:>6.3f}")

    print("\n  confusion (expected down, predicted across)")
    header = "".join(f"{r[:6]:>8}" for r in [*ROUTES, "none"])
    print(f"    {'':<14}{header}")
    for expected, row in report.confusion.items():
        cells = "".join(f"{row[p]:>8}" for p in [*ROUTES, "none"])
        print(f"    {expected:<14}{cells}")

    print(f"\n  rule engine fired on       {report.rule_fired_rate:.3f} of tickets")
    print(f"  rule engine precision      {report.rule_precision:.3f}   (correct where it fires)")
    print(f"  rules/model disagreement   {report.disagreement_rate:.3f}   (the hard-case signal)")

    # Aggregate last, on purpose.
    print(f"\n  OVERALL                    {report.overall:.3f}   (gate {OVERALL_GATE:.2f})")
    print(f"  {'GATE GREEN' if report.passed else 'GATE RED'}\n")


def evaluate(
    *, no_model: bool = False, engine: str | None = None, limit: int | None = None,
    sample: bool = False,
) -> RouteReport:
    from src.graph import nodes
    from src.graph.graph_state import initial_state, new_run_id
    from src.graph.support_graph import walk_graph
    from src.memory.customer_thread_store import CustomerThreadStore
    from src.utils.schemas import load_expected_routes, load_tickets

    if engine:
        from src.retrieval.retriever import build_default_retriever

        nodes.set_retriever(build_default_retriever(engine=engine))

    paths = app_config()["paths"]
    source = "data/tickets/sample_ticket_batch.json" if sample else paths["tickets"]
    tickets = load_tickets(resolve(source))
    labels = load_expected_routes(resolve("data/evaluation/expected_routes.json"))
    if limit:
        tickets = tickets[:limit]

    CustomerThreadStore.reset_default()
    run_id = new_run_id()
    results: list[CaseResult] = []

    for ticket in tickets:
        label = labels.get(ticket.ticket_id)
        if label is None:
            continue
        state = initial_state(ticket, run_id=run_id, no_model=no_model)
        try:
            final = walk_graph(dict(state))
        except Exception as exc:  # one bad ticket must not end a 150-ticket run
            log.exception("%s failed", ticket.ticket_id)
            final = {"route": None, "route_rationale": f"run failed: {exc}"}

        results.append(
            CaseResult(
                ticket_id=ticket.ticket_id,
                expected=label.route,
                predicted=final.get("route"),
                difficulty=label.difficulty,
                category=label.category,
                expected_target=label.escalation_target,
                predicted_target=final.get("escalation_target"),
                rule_route=final.get("rule_route"),
                llm_route=final.get("llm_route"),
                confidence=float(final.get("confidence", 0.0)),
                rationale=str(final.get("route_rationale", ""))[:200],
            )
        )
    return score(results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-model", action="store_true",
                        help="deterministic layers only -- the floor, needs no API key")
    parser.add_argument("--engine", choices=("hybrid", "dense", "bm25"), default=None)
    parser.add_argument("--sample", action="store_true", help="the 13-ticket dev batch")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--show-errors", type=int, default=10)
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)-7s %(message)s")
    report = evaluate(
        no_model=args.no_model, engine=args.engine, limit=args.limit, sample=args.sample
    )
    label = "(deterministic only)" if args.no_model else "(full pipeline)"
    print_report(report, label=label)

    if args.show_errors:
        errors = [c for c in report.cases if c["predicted"] != c["expected"]]
        print(f"  {len(errors)} misses; first {min(args.show_errors, len(errors))}:")
        for case in errors[: args.show_errors]:
            print(f"    {case['ticket_id']} [{case['difficulty']:<8}] "
                  f"want {case['expected']:<14} got {str(case['predicted']):<14}")
            print(f"        {case['rationale']}")

    if not args.no_save:
        directory = resolve(app_config()["paths"]["outputs"]) / "evaluation_reports"
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = directory / f"route_eval_{stamp}.json"
        path.write_text(json.dumps(asdict(report), indent=1, default=str), encoding="utf-8")
        print(f"\n  report written to {path}")

    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
