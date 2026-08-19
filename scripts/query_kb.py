#!/usr/bin/env python3
"""
Ask the index a question and look at what comes back. No LLM involved.

    python scripts/query_kb.py "my overdraft fee from last week, can I get it back"
    python scripts/query_kb.py --ticket TCK-1001
    python scripts/query_kb.py --ticket TCK-1084 --raw     # compare raw message vs built query
    python scripts/query_kb.py                              # interactive

Spend ten minutes here before writing a single graph node. Retrieval failures are almost
always obvious the moment you look at the scores, and almost always invisible once they are
buried three nodes deep in a prompt.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.retrieval.query_builder import from_ticket  # noqa: E402
from src.retrieval.retriever import build_default_retriever  # noqa: E402
from src.utils.config import app_config, resolve  # noqa: E402


def show(retriever, query: str, *, sentiment: str, category: str, product_area: str) -> None:
    result = retriever.retrieve(
        query, sentiment=sentiment, category=category, product_area=product_area
    )
    print(f"\nquery: {query}")
    print(f"top-1 similarity: {result.top_similarity:.3f}   "
          f"below_floor={result.below_floor}   scope_signal={result.scope_signal}")
    print("-" * 100)
    for i, hit in enumerate(result.hits, 1):
        score = "injected" if hit.similarity is None else f"{hit.similarity:.3f}  "
        flag = "" if hit.citable else "  [not citable]"
        print(f"{i:2d}. {score}  {hit.label:14s} {hit.source_file:28s} "
              f"{hit.title[:40]}{flag}")
        first_line = hit.text.splitlines()[1] if "\n" in hit.text else hit.text
        print(f"        {first_line[:96]}")
    if result.rejected:
        print(f"\n  below floor ({retriever.similarity_floor}): "
              + ", ".join(f"{h.label}@{h.similarity:.2f}" for h in result.rejected[:6]))
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="*", help="free-text query")
    parser.add_argument("--ticket", help="use a ticket ID from synthetic_tickets.json")
    parser.add_argument("--raw", action="store_true",
                        help="also search with the raw message, to see the difference")
    parser.add_argument("--sentiment", default="")
    args = parser.parse_args()

    retriever = build_default_retriever()

    if args.ticket:
        raw = json.loads(
            resolve(app_config()["paths"]["tickets"]).read_text(encoding="utf-8")
        )
        tickets = {t["ticket_id"]: t for t in (raw["tickets"] if isinstance(raw, dict) else raw)}
        ticket = tickets.get(args.ticket)
        if ticket is None:
            print(f"no such ticket: {args.ticket}")
            return 1
        print(f"\n=== {ticket['ticket_id']}  [{ticket['category']} / "
              f"{ticket['product_area']}] ===\n{ticket['message'][:500]}")
        show(retriever, from_ticket(ticket), sentiment=args.sentiment,
             category=ticket.get("category", ""), product_area=ticket.get("product_area", ""))
        if args.raw:
            print("=== same ticket, raw message as the query (the naive approach) ===")
            show(retriever, ticket["message"], sentiment=args.sentiment,
                 category=ticket.get("category", ""),
                 product_area=ticket.get("product_area", ""))
        return 0

    if args.query:
        show(retriever, " ".join(args.query), sentiment=args.sentiment,
             category="", product_area="")
        return 0

    print("interactive mode -- blank line or Ctrl-D to quit")
    while True:
        try:
            q = input("\n> ").strip()
        except EOFError:
            return 0
        if not q:
            return 0
        show(retriever, q, sentiment=args.sentiment, category="", product_area="")


if __name__ == "__main__":
    raise SystemExit(main())
