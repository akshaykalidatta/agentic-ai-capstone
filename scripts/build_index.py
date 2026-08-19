#!/usr/bin/env python3
"""
Build (or refresh) the knowledge-base vector index.

    python scripts/build_index.py                # incremental: skip unchanged files
    python scripts/build_index.py --force        # re-embed everything
    python scripts/build_index.py --dry-run      # parse + chunk only, no model, no writes
    python scripts/build_index.py --show-chunks  # print the chunk table

This is a **one-off offline job**, not part of the agent. Nothing here imports LangGraph and
nothing here is on the request path. You run it when the KB markdown changes; the graph
just opens the resulting `.chroma/` directory and reads. Keeping ingestion out of the graph
is the whole reason a 150-ticket eval run takes minutes instead of hours.

The incremental skip is keyed on a SHA-256 of each source file. The KB is hand-edited, so
you will re-index often, and re-embedding 84 chunks is only a few seconds -- but the habit
matters once a KB has thousands of chunks.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.retrieval.chunking import ChunkingConfig, chunk_all, estimate_tokens  # noqa: E402
from src.retrieval.document_loader import load_kb  # noqa: E402
from src.utils.config import app_config, resolve, routing_rules  # noqa: E402

EXPECTED_CLAUSE_COUNT = 59  # the KB has 59 numbered clauses; drift here means a parser bug


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-embed every file")
    parser.add_argument("--dry-run", action="store_true", help="parse and chunk only")
    parser.add_argument("--show-chunks", action="store_true", help="print every chunk")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    log = logging.getLogger("build_index")

    cfg = app_config()
    ret_cfg = cfg["retrieval"]
    chunk_cfg_raw = ret_cfg["chunking"]
    kb_dir = resolve(cfg["paths"]["knowledge_base"])

    chunk_cfg = ChunkingConfig(
        max_tokens=chunk_cfg_raw["max_tokens"],
        overlap_tokens=chunk_cfg_raw["overlap_tokens"],
        embed_doc_title=chunk_cfg_raw.get("embed_doc_title", True),
        embed_section_title=chunk_cfg_raw.get("embed_section_title", True),
        embed_scope_note=chunk_cfg_raw.get("embed_scope_note", False),
        non_citable_policy_ids=tuple(routing_rules().get("non_citable_policy_ids", [])),
    )

    # ------------------------------------------------------------------- parse and chunk
    docs = load_kb(kb_dir)
    log.info("parsed %d KB documents from %s", len(docs), kb_dir)

    embedder = None
    count_tokens = estimate_tokens
    if not args.dry_run:
        from src.retrieval.vector_store import Embedder

        emb_cfg = ret_cfg["embedding"]
        embedder = Embedder(
            emb_cfg["model_name"],
            normalize=emb_cfg.get("normalize", True),
            query_prefix=emb_cfg.get("query_prefix", ""),
            batch_size=emb_cfg.get("batch_size", 32),
        )
        count_tokens = embedder.count_tokens
        if chunk_cfg.max_tokens > embedder.max_seq_length:
            log.error(
                "chunking.max_tokens=%d exceeds the model's max_seq_length=%d. Chunks "
                "would be TRUNCATED SILENTLY at embed time -- fix app_config.yaml.",
                chunk_cfg.max_tokens,
                embedder.max_seq_length,
            )
            return 2

    chunks = chunk_all(docs, chunk_cfg, count_tokens)

    # ------------------------------------------------------------------------- integrity
    by_type = Counter(c.metadata["chunk_type"] for c in chunks)
    policy_ids = {c.policy_id for c in chunks if c.policy_id}
    log.info(
        "%d chunks: %d clause (%d distinct policy IDs), %d scope, %d section",
        len(chunks),
        by_type["clause"],
        len(policy_ids),
        by_type["scope"],
        by_type["section"],
    )
    if len(policy_ids) != EXPECTED_CLAUSE_COUNT:
        log.error(
            "expected %d distinct policy IDs, parsed %d. A clause heading probably lost "
            "its em dash or its ID format. Not indexing a partial KB.",
            EXPECTED_CLAUSE_COUNT,
            len(policy_ids),
        )
        return 2

    oversized = [c for c in chunks if c.metadata["token_estimate"] > chunk_cfg.max_tokens]
    if oversized:
        log.error("%d chunks exceed the token ceiling: %s", len(oversized),
                  [c.chunk_id for c in oversized])
        return 2

    longest = max(chunks, key=lambda c: c.metadata["token_estimate"])
    log.info(
        "longest chunk %s at %d tokens (ceiling %d)",
        longest.chunk_id,
        longest.metadata["token_estimate"],
        chunk_cfg.max_tokens,
    )

    if args.show_chunks:
        print(f"\n{'chunk_id':58s} {'type':8s} {'tok':>4s}  section")
        print("-" * 110)
        for c in chunks:
            print(
                f"{c.chunk_id:58s} {c.metadata['chunk_type']:8s} "
                f"{c.metadata['token_estimate']:4d}  {c.metadata['section'][:38]}"
            )
        print()

    if args.dry_run:
        log.info("dry run: nothing embedded, nothing written")
        return 0

    # ------------------------------------------------------------------------- index it
    from src.retrieval.vector_store import KBVectorStore

    store = KBVectorStore(
        resolve(cfg["paths"]["chroma_dir"]),
        collection_name=ret_cfg.get("collection_name", "northgate_kb"),
        embedder=embedder,
    )
    indexed = {} if args.force else store.indexed_hashes()

    written = 0
    for doc in docs:
        doc_chunks = [c for c in chunks if c.metadata["source_file"] == doc.source_file]
        if indexed.get(doc.source_file) == doc.content_hash:
            log.info("  %-32s unchanged (%s) - skipped", doc.source_file, doc.content_hash)
            continue
        store.delete_source(doc.source_file)  # drop stale chunks, incl. renamed clauses
        written += store.upsert(doc_chunks)
        log.info("  %-32s embedded %d chunks", doc.source_file, len(doc_chunks))

    total = store.count()
    log.info("index at %s holds %d chunks (%d written this run)",
             resolve(cfg["paths"]["chroma_dir"]), total, written)

    if total != len(chunks):
        log.warning(
            "index holds %d chunks but the KB parses to %d. Stale entries from an earlier "
            "run? Re-run with --force.", total, len(chunks)
        )

    missing = policy_ids - store.all_policy_ids()
    if missing:
        log.error("policy IDs missing from the index: %s", sorted(missing))
        return 2

    log.info("OK - all %d policy IDs are retrievable", len(policy_ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
