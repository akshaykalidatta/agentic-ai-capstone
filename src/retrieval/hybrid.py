"""
Hybrid retrieval: dense + BM25, fused by Reciprocal Rank Fusion.

Presents the `KBVectorStore` interface, so `Retriever` treats it as just another store and
needs no changes. Hybrid is a decorator, not a fork in the retrieval code.

## Why RRF and not a weighted score blend

Cosine similarity lives in 0..1 and is fairly flat (0.42 vs 0.51 is a real gap here). BM25 is
unbounded and scales with query length and term rarity -- a clause-ID match can score 12 while
a good topical match scores 3. Blending them with weights means picking a normalisation, and
every normalisation is wrong for some query.

RRF throws the scores away and keeps only the **ranks**:

    fused(chunk) = sum over lists of  1 / (RRF_K + rank)

which is scale-free by construction. `RRF_K = 60` is the value from the original paper; it
damps the difference between rank 1 and rank 2 so a single list cannot dominate on its own.

## What is deliberately preserved

The dense cosine survives on every hit that dense retrieved, because the similarity floor and
the absence-detection signal were calibrated against it. Hybrid changes the **ranking**; it
does not change what "no policy covers this" means. A chunk found only by BM25 carries
`similarity=None`, and `RetrievalResult.below_floor` -- "no dense hit survived the floor" --
therefore keeps working exactly as it did in P1.
"""

from __future__ import annotations

import logging
from typing import Any

from src.retrieval.bm25 import BM25Index

log = logging.getLogger(__name__)

RRF_K = 60


class HybridIndex:
    """
    Wraps a dense store and a BM25 index behind one `query`.

    Both are over-fetched well past `k`, because fusion can only reorder what it was given: a
    chunk at dense rank 40 that BM25 ranks 1st is exactly the case hybrid exists to rescue,
    and it is invisible if dense was only asked for 10.
    """

    mode = "hybrid"

    def __init__(
        self,
        dense_store: Any,
        sparse_index: BM25Index,
        *,
        candidate_pool: int = 30,
        rrf_k: int = RRF_K,
    ) -> None:
        self.dense_store = dense_store
        self.sparse_index = sparse_index
        self.candidate_pool = candidate_pool
        self.rrf_k = rrf_k
        sparse_index.verify_matches(dense_store.count())

    def count(self) -> int:
        return self.dense_store.count()

    def all_policy_ids(self) -> set[str]:
        return self.dense_store.all_policy_ids()

    def get_by_policy_ids(self, policy_ids: list[str]) -> list[dict[str, Any]]:
        # Guaranteed-context injection: the dense store is the authority on chunk text, and
        # these clauses are fetched by ID, so there is nothing for BM25 to contribute.
        return self.dense_store.get_by_policy_ids(policy_ids)

    def query(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        pool = max(self.candidate_pool, k * 3)
        dense_hits = self.dense_store.query(query, k=pool)
        sparse_hits = self.sparse_index.query(query, k=pool)

        by_chunk_id: dict[str, dict[str, Any]] = {}
        fused_scores: dict[str, float] = {}

        for rank, hit in enumerate(dense_hits, start=1):
            chunk_id = hit["chunk_id"]
            by_chunk_id[chunk_id] = dict(hit)
            fused_scores[chunk_id] = 1.0 / (self.rrf_k + rank)

        for rank, hit in enumerate(sparse_hits, start=1):
            chunk_id = hit["chunk_id"]
            contribution = 1.0 / (self.rrf_k + rank)
            if chunk_id in by_chunk_id:
                # Seen by both. Keep the dense record -- it owns the cosine the floor reads --
                # and add the lexical evidence alongside it.
                by_chunk_id[chunk_id]["bm25_score"] = hit.get("bm25_score")
                fused_scores[chunk_id] += contribution
            else:
                # BM25-only. `similarity=None` marks it as carrying no dense evidence, which
                # is what keeps absence detection honest.
                lexical_only = dict(hit)
                lexical_only["similarity"] = None
                by_chunk_id[chunk_id] = lexical_only
                fused_scores[chunk_id] = contribution

        ranked = sorted(fused_scores.items(), key=lambda pair: (-pair[1], pair[0]))
        results = []
        for chunk_id, score in ranked[:k]:
            result = by_chunk_id[chunk_id]
            result["fused_score"] = round(score, 6)
            results.append(result)
        return results


def build_sparse_index() -> BM25Index:
    """The BM25 index, built from the knowledge-base markdown. ~10 ms, no dependencies."""
    return BM25Index.from_knowledge_base()
