"""
Reconstruct a decision from its audit record, without re-running the agent.

HLD §8.1 sets the test of sufficiency as a question: *could you defend this decision six months
from now, without re-running the agent?* This module is that question turned into a command.

    python -m src.logging.replay --latest --ticket TCK-1143
    python -m src.logging.replay --run 20260821T171714Z-0a04 --check

`--check` is the P6 gate: it verifies every record in a run carries the evidence the decision
rested on, and exits non-zero if any does not. A record that is merely *present* is not a
record that is replayable -- "eligible" is an assertion, "eligible, no prior reversal in 12
months, fee 7 days old" is evidence, and only the second survives a challenge.
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Any

from src.utils.config import app_config, resolve

# What a record must carry to stand on its own, whichever path it took.
ALWAYS_REQUIRED: tuple[tuple[str, str], ...] = (
    ("route", "the decision itself"),
    ("route_rationale", "why, in words"),
    ("config_hash", "which thresholds were in force"),
    ("confidence_parts", "how the confidence was arrived at, not just its value"),
    ("trace", "which nodes ran"),
)

# Required only of tickets that went through the normal path. A safety-bypass ticket has no
# retrieval log and no preconditions *by design* -- the branch exists precisely so that no
# knowledge-base text reaches a crisis reply. Demanding them here would report the bypass
# working correctly as a broken audit record, which is how a check trains people to ignore it.
REQUIRED_UNLESS_BYPASSED: tuple[tuple[str, str], ...] = (
    ("retrieval_log", "what was searched for and what came back, per attempt"),
    ("preconditions", "the computed facts, with their inputs"),
)

# What a bypassed ticket must carry instead: the flag that triggered it, and proof the context
# really was empty.
REQUIRED_WHEN_BYPASSED: tuple[tuple[str, str], ...] = (
    ("safety_flags", "which flag sent this down the bypass"),
)


def audit_directory() -> Path:
    return resolve(app_config()["paths"]["outputs"]) / "audit_logs"


def list_runs() -> list[Path]:
    """Newest last. Run ids are timestamp-prefixed, so lexical order is chronological."""
    return sorted(audit_directory().glob("run_*.jsonl"))


def load_run(run_id: str | None = None, *, latest: bool = False) -> list[dict[str, Any]]:
    if latest or run_id is None:
        runs = list_runs()
        if not runs:
            raise FileNotFoundError(f"no audit logs in {audit_directory()}")
        path = runs[-1]
    else:
        path = audit_directory() / f"run_{run_id}.jsonl"
        if not path.is_file():
            raise FileNotFoundError(f"no such run: {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def missing_evidence(record: dict[str, Any]) -> list[str]:
    """
    Which required fields are absent or empty. Empty list means the record is replayable.

    What counts as required depends on the path the ticket took -- see the constants above.
    """
    bypassed = record.get("retrieval_mode") == "bypassed"
    required = list(ALWAYS_REQUIRED)
    required += list(REQUIRED_WHEN_BYPASSED if bypassed else REQUIRED_UNLESS_BYPASSED)

    gaps = []
    for key, description in required:
        value = record.get(key)
        if value in (None, "", [], {}):
            gaps.append(f"{key} ({description})")

    if bypassed and record.get("retrieved"):
        # The whole point of the branch. If this ever fires, a crisis reply was drafted with
        # policy text in the context window.
        gaps.append("retrieved is non-empty on a bypassed ticket -- the bypass leaked")

    # A precondition without its inputs is a verdict, not evidence -- the specific failure
    # this check exists to catch, because the field is present and looks fine.
    for name, precondition in (record.get("preconditions") or {}).items():
        if precondition.get("met") is not None and not precondition.get("inputs"):
            gaps.append(f"preconditions.{name}.inputs (a verdict with nothing behind it)")
    return gaps


def render(record: dict[str, Any]) -> str:
    """The decision chain, in the order it was made."""
    out: list[str] = []
    add = out.append

    ticket = record.get("ticket", {})
    add(f"=== {record.get('ticket_id')} — {ticket.get('subject', '')}")
    add(f"    run {record.get('run_id')}  config {record.get('config_hash')}  "
        f"mode {record.get('hitl_mode')}")
    add(f"    {ticket.get('category')} / {ticket.get('product_area')}  "
        f"priority {ticket.get('priority')}")

    history = record.get("customer_history") or []
    if history:
        add("\n--- what we already knew about this customer")
        for entry in history:
            add(f"    {entry.get('created_at', '')[:10]} {entry.get('ticket_id')}: "
                f"{entry.get('disposition')}")

    add("\n--- triage")
    add(f"    sentiment {record.get('sentiment')}   intent {record.get('intent') or '(none)'}")
    for flag in record.get("safety_flags") or []:
        add(f"    FLAG {flag.get('code')} [{flag.get('detector')}] {flag.get('evidence_span','')[:90]}")

    add("\n--- computed facts")
    for name, precondition in (record.get("preconditions") or {}).items():
        verdict = {True: "YES", False: "NO ", None: "?? "}[precondition.get("met")]
        add(f"    {verdict} {name}: {precondition.get('reason')}")
        add(f"        from {precondition.get('inputs')}")

    add("\n--- retrieval")
    add(f"    mode {record.get('retrieval_mode')}")
    for attempt in record.get("retrieval_log") or []:
        add(f"    attempt {attempt.get('attempt')}: top={attempt.get('top_similarity')} "
            f"ids={','.join(attempt.get('policy_ids') or []) or '-'}")
        add(f"        query: {attempt.get('query', '')[:120]}")

    analysis = record.get("policy_analysis") or {}
    add("\n--- reasoning")
    add(f"    verified {analysis.get('policy_verified')}   "
        f"deciding {[c.get('policy_id') for c in analysis.get('deciding_clauses') or []]}")
    if analysis.get("missing_facts"):
        add(f"    missing: {analysis['missing_facts']}")

    add("\n--- decision")
    add(f"    rules proposed {record.get('rule_route')}   model proposed {record.get('llm_route')}")
    add(f"    ROUTE {record.get('route')}  ->  {record.get('escalation_target') or 'no queue'}"
        + ("" if record.get("escalation_visible_to_customer", True) else "   [NOT VISIBLE TO CUSTOMER]"))
    add(f"    {record.get('route_rationale')}")
    add(f"    confidence {record.get('confidence')}  {record.get('confidence_parts')}")
    loops = record.get("loops") or {}
    if record.get("loops_capped"):
        add(f"    loops {loops}  CAPPED: {record['loops_capped']}")

    add("\n--- reply")
    add(f"    cites {record.get('cited_policy_ids') or '-'}")
    for line in (record.get("draft") or "").splitlines():
        add(f"    | {line}")
    validation = record.get("validation") or {}
    if not validation.get("ok", True):
        add(f"    VALIDATION FAILED: {validation}")

    reviewer = record.get("reviewer") or {}
    if reviewer:
        add(f"\n--- review\n    {reviewer.get('action')} by {reviewer.get('reviewer')} "
            f"({reviewer.get('mode')} mode)")

    gaps = missing_evidence(record)
    add(f"\n--- replayable: {'YES' if not gaps else 'NO — missing ' + ', '.join(gaps)}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--run", help="run id, e.g. 20260821T171714Z-0a04")
    source.add_argument("--latest", action="store_true", help="the most recent run")
    parser.add_argument("--ticket", help="one ticket; omit to walk the whole run")
    parser.add_argument("--check", action="store_true",
                        help="verify every record is replayable and exit non-zero if not")
    args = parser.parse_args(argv)

    records = load_run(args.run, latest=args.latest or not args.run)

    if args.check:
        incomplete = [(r["ticket_id"], missing_evidence(r)) for r in records]
        incomplete = [(t, g) for t, g in incomplete if g]
        print(f"{len(records)} records checked, {len(incomplete)} incomplete")
        for ticket_id, gaps in incomplete[:20]:
            print(f"  {ticket_id}: {', '.join(gaps)}")
        return 1 if incomplete else 0

    for record in records:
        if args.ticket and record.get("ticket_id") != args.ticket:
            continue
        print(render(record))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
