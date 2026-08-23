"""
Run every evaluator over one run and write the report.

    python -m src.evaluation.report --latest
    python -m src.evaluation.report --run 20260821T174015Z-282f --markdown

Reads audit records, so it needs no model, no index and no API key -- you can re-score a run
from six months ago, or re-score today's run after changing an evaluator, without spending a
single call. That separation is the point of the audit log carrying evidence rather than
verdicts.

Output order follows HLD §8.2: **critical errors first, hard subset second, aggregate last.**
Putting the aggregate at the top is how a project talks itself into believing it is finished --
it inflates on the 65 easy tickets and says very little about the design.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.evaluation.evaluators import ALL_EVALUATORS, EvaluatorResult, load_labels
from src.logging.replay import load_run, missing_evidence
from src.utils.config import app_config, resolve


def critical_errors(records: list[dict[str, Any]], labels) -> dict[str, list[str]]:
    """
    The two error classes whose real-world cost is not comparable to an ordinary miss.

    Computed here rather than imported from `route_eval` because that module runs the
    pipeline; this one reads a finished run, and P8 must be able to score a run it did not
    produce.
    """
    wrongly_refused: list[str] = []
    wrongly_auto_resolved: list[str] = []
    safety_sensitive = {"conduct_and_prohibited", "disputes_and_fees"}

    for record in records:
        label = labels.get(record.get("ticket_id", ""))
        if label is None:
            continue
        predicted, expected = record.get("route"), label.expected_route
        if predicted == "REFUSE" and expected in {"AUTO_RESOLVE", "ESCALATE"}:
            wrongly_refused.append(record["ticket_id"])
        if (
            predicted == "AUTO_RESOLVE"
            and expected == "ESCALATE"
            and label.category in safety_sensitive
        ):
            wrongly_auto_resolved.append(record["ticket_id"])

    return {
        "wrongly_refused": wrongly_refused,
        "wrongly_auto_resolved": wrongly_auto_resolved,
    }


def build(records: list[dict[str, Any]]) -> dict[str, Any]:
    labels = load_labels()
    results: list[EvaluatorResult] = [evaluate(records, labels) for evaluate in ALL_EVALUATORS]
    criticals = critical_errors(records, labels)
    scored = [r for r in records if r.get("ticket_id") in labels]
    incomplete = [r["ticket_id"] for r in records if missing_evidence(r)]

    hard = [r for r in scored if labels[r["ticket_id"]].is_hard]
    accuracy = lambda rows: (  # noqa: E731 -- local, and a def here would be noise
        round(
            sum(1 for r in rows if r.get("route") == labels[r["ticket_id"]].expected_route)
            / len(rows),
            4,
        )
        if rows
        else 0.0
    )

    gates_failed = [r.name for r in results if r.passed is False]
    if criticals["wrongly_refused"] or criticals["wrongly_auto_resolved"]:
        gates_failed.append("critical errors")
    if incomplete:
        gates_failed.append("audit replayability")

    return {
        "run_id": records[0].get("run_id") if records else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config_hash": records[0].get("config_hash") if records else None,
        "hitl_mode": records[0].get("hitl_mode") if records else None,
        "records": len(records),
        "scored_against_golden": len(scored),
        "critical_errors": criticals,
        "route_accuracy_hard": accuracy(hard),
        "route_accuracy_scored": accuracy(scored),
        "audit_incomplete": incomplete,
        "evaluators": [asdict(r) for r in results],
        "gates_failed": gates_failed,
        "passed": not gates_failed,
    }


def print_report(report: dict[str, Any]) -> None:
    print(f"\n=== evaluation report — run {report['run_id']}")
    print(f"  config {report['config_hash']}   hitl mode {report['hitl_mode']}")
    print(f"  {report['records']} records, {report['scored_against_golden']} with full labels")

    criticals = report["critical_errors"]
    print("\n  CRITICAL ERRORS (target: zero)")
    print(f"    wrongly refused         {len(criticals['wrongly_refused']):>3}  "
          f"{criticals['wrongly_refused'][:5] or ''}")
    print(f"    wrongly auto-resolved   {len(criticals['wrongly_auto_resolved']):>3}  "
          f"{criticals['wrongly_auto_resolved'][:5] or ''}")

    print(f"\n  route accuracy, hard subset   {report['route_accuracy_hard']:.3f}")

    print("\n  evaluators")
    for entry in report["evaluators"]:
        result = EvaluatorResult(**entry)
        print(result.line())

    incomplete = report["audit_incomplete"]
    print(f"\n  audit records replayable      "
          f"{report['records'] - len(incomplete)}/{report['records']}")
    if incomplete:
        print(f"    incomplete: {incomplete[:8]}")

    calibration = next(
        (e["detail"].get("calibration_by_decile") for e in report["evaluators"]
         if e["name"] == "confidence in-band"),
        None,
    )
    if calibration:
        print("\n  confidence calibration (accuracy by decile)")
        for band, stats in calibration.items():
            if stats["n"]:
                print(f"    {band}   n={stats['n']:>3}   accuracy {stats['accuracy']:.3f}")

    # Aggregate last, on purpose.
    print(f"\n  route accuracy, all scored    {report['route_accuracy_scored']:.3f}")
    print(f"  {'ALL GATES GREEN' if report['passed'] else 'GATES FAILED: ' + str(report['gates_failed'])}\n")


def to_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Evaluation report — run `{report['run_id']}`",
        "",
        f"- generated: {report['generated_at']}",
        f"- config hash: `{report['config_hash']}`",
        f"- HITL mode: **{report['hitl_mode']}** — every number below is only comparable to "
        "another run in the same mode",
        f"- records: {report['records']} ({report['scored_against_golden']} with full labels)",
        "",
        "## Critical errors",
        "",
        "| Class | Count | Tickets |",
        "| --- | --- | --- |",
        f"| Wrongly refused | {len(report['critical_errors']['wrongly_refused'])} | "
        f"{', '.join(report['critical_errors']['wrongly_refused'][:8]) or '—'} |",
        f"| Wrongly auto-resolved | {len(report['critical_errors']['wrongly_auto_resolved'])} | "
        f"{', '.join(report['critical_errors']['wrongly_auto_resolved'][:8]) or '—'} |",
        "",
        f"Route accuracy on the hard subset: **{report['route_accuracy_hard']:.3f}**",
        "",
        "## Evaluators",
        "",
        "| Evaluator | Score | n | Gate | Verdict |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in report["evaluators"]:
        result = EvaluatorResult(**entry)
        verdict = {True: "PASS", False: "**FAIL**", None: "—"}[result.passed]
        gate = f"{result.gate:.2f}" if result.gate is not None else "—"
        lines.append(f"| {result.name} | {result.score:.3f} | {result.n} | {gate} | {verdict} |")

    lines += [
        "",
        f"Audit records replayable: "
        f"{report['records'] - len(report['audit_incomplete'])}/{report['records']}",
        "",
        f"## Aggregate (last, on purpose)",
        "",
        f"Route accuracy over all scored tickets: **{report['route_accuracy_scored']:.3f}**",
        "",
        "It inflates on the easy tickets. The hard subset and the critical-error counts above "
        "are the numbers that say something about the design.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--run", help="run id")
    source.add_argument("--latest", action="store_true")
    parser.add_argument("--markdown", action="store_true", help="also write a .md alongside")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args(argv)

    records = load_run(args.run, latest=args.latest or not args.run)
    report = build(records)
    print_report(report)

    if not args.no_save:
        directory = resolve(app_config()["paths"]["outputs"]) / "evaluation_reports"
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"report_{report['run_id']}"
        (directory / f"{stem}.json").write_text(
            json.dumps(report, indent=1, default=str), encoding="utf-8"
        )
        if args.markdown:
            (directory / f"{stem}.md").write_text(to_markdown(report), encoding="utf-8")
        print(f"  written to {directory / stem}.json"
              + (f" and .md" if args.markdown else ""))

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
