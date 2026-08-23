"""
The P1 gate: does retrieval actually find the right policy?

Why a gate exists at all
------------------------
Everything downstream is a function of what retrieval returns. If the right clause is not
in the context, the analysis node cannot reason about it, the router cannot route on it, and
the drafting node will invent a plausible-sounding fee limit instead -- and you will spend a
week tuning prompts to fix a problem that lives in this file. So: no LangGraph work until
this number is green.

    doc recall@5 >= 0.90        <- the gate from the build plan

Three metrics, and the difference between them matters
------------------------------------------------------
`doc_recall`      -- did the right *file* come back? Coarse, and the gate. If this is bad,
                     chunking or query construction is broken.
`clause_recall`   -- did the right *clause* come back? Strictly harder, and the number that
                     actually predicts groundedness in P4. Reported dense-only and again
                     with guaranteed-context injection, because injection can flatter a
                     score without the embedder having done anything.
`absence`         -- on the 8 tickets whose answer is "no policy covers this", does the
                     similarity floor fire? And -- the failure nobody checks -- does it
                     *wrongly* fire on the 99 tickets that do have a policy?

Usage
-----
    python -m src.evaluation.retrieval_eval                       # run the gate
    python -m src.evaluation.retrieval_eval --sweep-floor 0.25,0.3,0.35,0.4
    python -m src.evaluation.retrieval_eval --sweep-k 3,5,8
    python -m src.evaluation.retrieval_eval --show-failures 15
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.retrieval.query_builder import from_ticket
from src.retrieval.retriever import Retriever, build_default_retriever
from src.utils.config import app_config, resolve

log = logging.getLogger(__name__)

DOC_RECALL_GATE = 0.90


@dataclass
class CaseResult:
    ticket_id: str
    difficulty: str
    category: str
    query: str
    expected_sources: list[str]
    retrieved_sources: list[str]  # dense only
    retrieved_sources_system: list[str]  # dense + guaranteed injection
    expected_policy_ids: list[str]
    retrieved_policy_ids: list[str]  # dense only
    retrieved_with_injection: list[str]
    top_similarity: float
    below_floor: bool
    scope_signal: bool
    no_policy_expected: bool

    @property
    def doc_recall(self) -> float | None:
        if not self.expected_sources:
            return None
        hit = len(set(self.expected_sources) & set(self.retrieved_sources))
        return hit / len(set(self.expected_sources))

    @property
    def doc_recall_system(self) -> float | None:
        """
        What the *model* actually sees, i.e. counting guaranteed-context injection.

        Reported next to `doc_recall` rather than instead of it. Injection always pulls in
        `abusive_content_policy.md` (CON-010/CON-011 are on for every ticket), so this
        number gets a free point on every ticket whose expected sources include the conduct
        policy. Useful as the system-level truth; useless for judging the embedder.
        """
        if not self.expected_sources:
            return None
        hit = len(set(self.expected_sources) & set(self.retrieved_sources_system))
        return hit / len(set(self.expected_sources))

    @property
    def clause_recall(self) -> float | None:
        if not self.expected_policy_ids:
            return None
        hit = len(set(self.expected_policy_ids) & set(self.retrieved_policy_ids))
        return hit / len(set(self.expected_policy_ids))

    @property
    def clause_recall_injected(self) -> float | None:
        if not self.expected_policy_ids:
            return None
        hit = len(set(self.expected_policy_ids) & set(self.retrieved_with_injection))
        return hit / len(set(self.expected_policy_ids))

    @property
    def missed_policy_ids(self) -> list[str]:
        return sorted(set(self.expected_policy_ids) - set(self.retrieved_with_injection))


@dataclass
class EvalReport:
    k: int
    similarity_floor: float
    n_cases: int
    doc_recall: float  # dense only -- this is the gate
    doc_recall_system: float  # dense + injection -- what the model sees
    doc_recall_hard: float
    full_doc_hit_rate: float
    clause_recall_dense: float
    clause_recall_injected: float
    absence_detected: float
    false_absence_rate: float
    mean_top_similarity: float
    passed: bool
    cases: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        return (
            f"k={self.k} floor={self.similarity_floor:.2f}  "
            f"doc_recall@{self.k}={self.doc_recall:.3f} (hard {self.doc_recall_hard:.3f})  "
            f"clause_recall={self.clause_recall_dense:.3f}"
            f"/{self.clause_recall_injected:.3f}(inj)  "
            f"absence={self.absence_detected:.2f}  "
            f"false_absence={self.false_absence_rate:.3f}  "
            f"[{verdict} gate {DOC_RECALL_GATE:.2f}]"
        )


def _mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 4) if values else 0.0


def load_cases() -> tuple[list[dict], dict[str, dict]]:
    cfg = app_config()
    golden = json.loads(resolve(cfg["paths"]["golden_dataset"]).read_text(encoding="utf-8"))
    tickets_raw = json.loads(resolve(cfg["paths"]["tickets"]).read_text(encoding="utf-8"))
    tickets = tickets_raw["tickets"] if isinstance(tickets_raw, dict) else tickets_raw
    return golden["records"], {t["ticket_id"]: t for t in tickets}


def evaluate(
    retriever: Retriever,
    *,
    k: int | None = None,
    similarity_floor: float | None = None,
    limit: int | None = None,
) -> EvalReport:
    records, tickets = load_cases()
    if limit:
        records = records[:limit]

    k = k if k is not None else retriever.k
    floor = similarity_floor if similarity_floor is not None else retriever.similarity_floor

    results: list[CaseResult] = []
    for rec in records:
        ticket = tickets.get(rec["ticket_id"])
        if ticket is None:
            log.warning("golden record %s has no matching ticket", rec["ticket_id"])
            continue

        query = from_ticket(ticket)
        # No triage node yet (P1), so no sentiment is passed. Guaranteed injection therefore
        # contributes only the `always` clauses -- which is honest: it measures what the
        # retrieval layer can do on its own.
        out = retriever.retrieve(
            query,
            k=k,
            similarity_floor=floor,
            category=ticket.get("category", ""),
            product_area=ticket.get("product_area", ""),
        )
        dense = [h for h in out.hits if not h.injected]
        results.append(
            CaseResult(
                ticket_id=rec["ticket_id"],
                difficulty=rec.get("difficulty", ""),
                category=rec.get("category", ""),
                query=query,
                expected_sources=list(rec.get("expected_kb_sources") or []),
                retrieved_sources=list(dict.fromkeys(h.source_file for h in dense)),
                retrieved_sources_system=list(dict.fromkeys(h.source_file for h in out.hits)),
                expected_policy_ids=list(rec.get("expected_policy_ids") or []),
                retrieved_policy_ids=[h.policy_id for h in dense if h.policy_id],
                retrieved_with_injection=[h.policy_id for h in out.hits if h.policy_id],
                top_similarity=out.top_similarity,
                below_floor=out.below_floor,
                scope_signal=out.scope_signal,
                no_policy_expected=bool(rec.get("no_policy_in_kb")),
            )
        )

    with_policy = [r for r in results if not r.no_policy_expected]
    no_policy = [r for r in results if r.no_policy_expected]
    hard = [r for r in with_policy if r.difficulty == "hard"]

    doc_recalls = [r.doc_recall for r in with_policy if r.doc_recall is not None]
    report = EvalReport(
        k=k,
        similarity_floor=floor,
        n_cases=len(results),
        doc_recall=_mean(doc_recalls),
        doc_recall_system=_mean(
            [r.doc_recall_system for r in with_policy if r.doc_recall_system is not None]
        ),
        doc_recall_hard=_mean([r.doc_recall for r in hard if r.doc_recall is not None]),
        full_doc_hit_rate=_mean([1.0 if r == 1.0 else 0.0 for r in doc_recalls]),
        clause_recall_dense=_mean(
            [r.clause_recall for r in with_policy if r.clause_recall is not None]
        ),
        clause_recall_injected=_mean(
            [r.clause_recall_injected for r in with_policy
             if r.clause_recall_injected is not None]
        ),
        # Of the tickets whose true answer is "not covered", how many did the floor catch?
        absence_detected=_mean(
            [1.0 if (r.below_floor or r.scope_signal) else 0.0 for r in no_policy]
        ),
        # The mirror-image error: a covered ticket that looks uncovered. This is the one
        # that quietly escalates easy tickets, so it is reported next to the other.
        false_absence_rate=_mean([1.0 if r.below_floor else 0.0 for r in with_policy]),
        mean_top_similarity=_mean([r.top_similarity for r in results]),
        passed=_mean(doc_recalls) >= DOC_RECALL_GATE,
        cases=[asdict(r) for r in results],
    )
    return report


def print_failures(report: EvalReport, limit: int) -> None:
    misses = [
        c
        for c in report.cases
        if not c["no_policy_expected"]
        and c["expected_sources"]
        and not set(c["expected_sources"]) <= set(c["retrieved_sources"])
    ]
    if not misses:
        print("\nno document-level misses.\n")
    else:
        print(f"\n{len(misses)} document-level miss(es):")
        for c in misses[:limit]:
            print(
                f"  {c['ticket_id']} [{c['difficulty']}] want={c['expected_sources']} "
                f"got={c['retrieved_sources']} top_sim={c['top_similarity']:.3f}\n"
                f"      query: {c['query'][:150]}"
            )

    clause_misses = [
        c
        for c in report.cases
        if c["expected_policy_ids"]
        and not set(c["expected_policy_ids"]) <= set(c["retrieved_with_injection"])
    ]
    print(f"\n{len(clause_misses)} clause-level miss(es) (harder than the gate):")
    for c in clause_misses[:limit]:
        missed = sorted(set(c["expected_policy_ids"]) - set(c["retrieved_with_injection"]))
        print(
            f"  {c['ticket_id']} [{c['difficulty']}] missed={missed} "
            f"got={c['retrieved_policy_ids']}"
        )
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=None)
    parser.add_argument("--floor", type=float, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sweep-floor", type=str, default="")
    parser.add_argument("--sweep-k", type=str, default="")
    parser.add_argument("--show-failures", type=int, default=10)
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument(
        "--engine",
        choices=("hybrid", "dense", "bm25"),
        default=None,
        help="hybrid (default) | dense = P1's vector-only slice | bm25 = lexical only, "
             "needs no index and no torch",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="run all three engines and print them side by side -- the only honest way to "
             "decide whether hybrid is earning its second index",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    if args.compare:
        print()
        for engine in ("bm25", "dense", "hybrid"):
            try:
                rep = evaluate(
                    build_default_retriever(engine=engine),
                    k=args.k, similarity_floor=args.floor, limit=args.limit,
                )
            except Exception as exc:
                print(f"  {engine:<8} unavailable: {exc}")
                continue
            print(f"  {engine:<8} doc={rep.doc_recall:.3f}  hard={rep.doc_recall_hard:.3f}  "
                  f"clause={rep.clause_recall_dense:.3f}  full={rep.full_doc_hit_rate:.3f}  "
                  f"absence={rep.absence_detected:.3f}  false_absence={rep.false_absence_rate:.3f}")
        print()
        return 0

    retriever = build_default_retriever(engine=args.engine)

    if args.sweep_floor or args.sweep_k:
        floors = (
            [float(x) for x in args.sweep_floor.split(",")]
            if args.sweep_floor
            else [args.floor if args.floor is not None else retriever.similarity_floor]
        )
        ks = (
            [int(x) for x in args.sweep_k.split(",")]
            if args.sweep_k
            else [args.k if args.k is not None else retriever.k]
        )
        print()
        for k in ks:
            for floor in floors:
                rep = evaluate(retriever, k=k, similarity_floor=floor, limit=args.limit)
                print("  " + rep.summary())
        print(
            "\nPick the (k, floor) that keeps doc_recall above the gate while maximising "
            "`absence` and keeping `false_absence` at or near zero. Those two move in "
            "opposite directions -- that trade-off is the whole point of the sweep.\n"
        )
        return 0

    report = evaluate(retriever, k=args.k, similarity_floor=args.floor, limit=args.limit)
    print("\n" + report.summary() + "\n")
    print(f"  cases evaluated          {report.n_cases}")
    print(f"  doc recall@{report.k}            {report.doc_recall:.3f}   "
          f"(gate {DOC_RECALL_GATE:.2f})")
    print(f"  doc recall, system view  {report.doc_recall_system:.3f}   (incl. injection)")
    print(f"  doc recall, hard only    {report.doc_recall_hard:.3f}")
    print(f"  all expected docs found  {report.full_doc_hit_rate:.3f}")
    print(f"  clause recall (dense)    {report.clause_recall_dense:.3f}")
    print(f"  clause recall (+inject)  {report.clause_recall_injected:.3f}")
    print(f"  absence detected (8)     {report.absence_detected:.3f}")
    print(f"  false absence (99)       {report.false_absence_rate:.3f}   (want 0.000)")
    print(f"  mean top-1 similarity    {report.mean_top_similarity:.3f}")

    if args.show_failures:
        print_failures(report, args.show_failures)

    if not args.no_save:
        out_dir = resolve(app_config()["paths"]["outputs"]) / "evaluation_reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = out_dir / f"retrieval_eval_{stamp}.json"
        path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
        print(f"report written to {path}")

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    raise SystemExit(main())
