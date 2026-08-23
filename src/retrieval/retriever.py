"""
The retriever: the one object the LangGraph `rag` node will call.

Everything the graph needs from retrieval is behind `Retriever.retrieve(...)`. That is
deliberate -- the graph node should be about ten lines that reads state, calls this, and
writes state. All the retrieval policy lives here where it can be tested and swept without
running a graph.

Three behaviours that a plain `similarity_search(query, k=5)` does not give us:

**Dedupe by policy_id.** TRB-002 is long enough to be indexed as two parts. Without dedupe
those two parts eat two of the five slots and crowd out a different clause. With dedupe
the clause appears once, scored at its best part.

**Stitch parts back together.** Retrieval matched a fragment; the *model* must see the whole
clause, because the conditions it has to check may live in the other fragment. Index-level
granularity and prompt-level granularity are different concerns.

**Guaranteed context.** Some clauses are too important to leave to a similarity score.
CON-011 ("what must never trigger a refusal") is injected on every single ticket. It is not
competing for one of the k slots -- it is added on top. Cost: ~150 tokens. Benefit: the
cheapest defence in the project against refusing a legitimate request from an angry
customer.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from typing import Any

from src.retrieval.vector_store import KBVectorStore

log = logging.getLogger(__name__)


@dataclass
class Hit:
    chunk_id: str
    policy_id: str
    source_file: str
    chunk_type: str
    section: str
    title: str
    text: str
    similarity: float | None  # dense cosine; None for injected clauses and BM25-only hits
    citable: bool
    injected: bool = False
    bm25_score: float | None = None  # lexical evidence, when hybrid is on
    fused_score: float | None = None  # RRF score that decided the rank

    @property
    def label(self) -> str:
        return self.policy_id or f"{self.source_file} § {self.title}"


@dataclass
class RetrievalResult:
    query: str
    hits: list[Hit] = field(default_factory=list)  # dense hits above floor, then injected
    rejected: list[Hit] = field(default_factory=list)  # dense hits below the floor
    top_similarity: float = 0.0

    @property
    def below_floor(self) -> bool:
        """
        First of the three absence-detection signals (LLD §3). Absence needs two of:
        top-1 below floor, a scope chunk saying the topic is out of scope, and analysis
        finding no deciding clause. This property is only the first one.
        """
        return not any(h.similarity is not None for h in self.hits)

    @property
    def scope_signal(self) -> bool:
        """Second signal: a scope note out-ranked every clause."""
        scored = [h for h in self.hits if h.similarity is not None]
        return bool(scored) and scored[0].chunk_type == "scope"

    def policy_ids(self, *, citable_only: bool = False) -> list[str]:
        return list(
            dict.fromkeys(
                h.policy_id
                for h in self.hits
                if h.policy_id and (h.citable or not citable_only)
            )
        )

    def source_files(self) -> list[str]:
        return list(dict.fromkeys(h.source_file for h in self.hits))

    def context_block(self, *, include_uncitable: bool = True) -> str:
        """
        Prompt-ready context. Each block is tagged with what the model is allowed to do
        with it, because "do not cite CON-010" only works if the prompt says which chunk
        is CON-010.
        """
        blocks: list[str] = []
        for h in self.hits:
            if not h.citable and not include_uncitable:
                continue
            tag = f"[{h.label}]"
            if not h.citable:
                tag += " (INTERNAL GUIDANCE - do not quote or cite to the customer)"
            elif h.injected:
                tag += " (always-on guidance)"
            else:
                tag += f" (similarity {h.similarity:.2f})"
            blocks.append(f"{tag}\nsource: {h.source_file}\n{h.text}")
        return "\n\n---\n\n".join(blocks)


def resolve_guaranteed_policy_ids(
    rules: dict[str, Any],
    *,
    sentiment: str = "",
    category: str = "",
    product_area: str = "",
    known_policy_ids: set[str] | None = None,
) -> list[str]:
    """
    Expand `config/routing_rules.yaml -> guaranteed_context` into concrete policy IDs.

    Patterns like `CON-*` are expanded against the IDs actually in the index, so adding a
    CON-012 to the KB picks it up automatically and a typo'd pattern expands to nothing
    instead of crashing.
    """
    section = (rules or {}).get("guaranteed_context", {}) or {}
    wanted: list[str] = list(section.get("always", []) or [])
    for key, value in (
        ("by_sentiment", sentiment),
        ("by_category", category),
        ("by_product_area", product_area),
    ):
        if value:
            wanted.extend((section.get(key, {}) or {}).get(value, []) or [])

    out: list[str] = []
    for entry in wanted:
        if any(ch in entry for ch in "*?["):
            matches = sorted(fnmatch.filter(known_policy_ids or set(), entry))
            if not matches:
                log.warning("guaranteed_context pattern %r matched no policy IDs", entry)
            out.extend(matches)
        else:
            out.append(entry)
    return list(dict.fromkeys(out))


def _rank_score(item: dict[str, Any]) -> float:
    """
    How good is this candidate, for dedupe purposes.

    Prefers the fused score when hybrid produced one, then the dense cosine. A BM25-only hit
    has `similarity=None`, so a bare `>` comparison here raises TypeError -- which is exactly
    what happened the first time hybrid was switched on.
    """
    fused = item.get("fused_score")
    if fused is not None:
        return float(fused)
    similarity = item.get("similarity")
    return float(similarity) if similarity is not None else 0.0


class Retriever:
    def __init__(
        self,
        store: KBVectorStore,
        *,
        k: int = 5,
        similarity_floor: float = 0.35,
        dedupe_by_policy_id: bool = True,
        stitch_clause_parts: bool = True,
        routing_rules: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self.k = k
        self.similarity_floor = similarity_floor
        self.dedupe_by_policy_id = dedupe_by_policy_id
        self.stitch_clause_parts = stitch_clause_parts
        self.routing_rules = routing_rules or {}
        self._policy_ids_cache: set[str] | None = None

    # ------------------------------------------------------------------------ internals

    def _known_policy_ids(self) -> set[str]:
        if self._policy_ids_cache is None:
            self._policy_ids_cache = self.store.all_policy_ids()
        return self._policy_ids_cache

    @staticmethod
    def _to_hit(raw: dict[str, Any], *, injected: bool = False) -> Hit:
        meta = raw.get("metadata", {})
        return Hit(
            chunk_id=raw["chunk_id"],
            policy_id=str(meta.get("policy_id", "")),
            source_file=str(meta.get("source_file", "")),
            chunk_type=str(meta.get("chunk_type", "")),
            section=str(meta.get("section", "")),
            title=str(meta.get("title", "")),
            text=raw.get("text", ""),
            similarity=raw.get("similarity"),
            citable=bool(meta.get("citable", False)),
            injected=injected,
            bm25_score=raw.get("bm25_score"),
            fused_score=raw.get("fused_score"),
        )

    def _stitch(self, hit: Hit, parts: list[dict[str, Any]]) -> Hit:
        """Reassemble a multi-part clause, dropping the overlap paragraphs."""
        ordered = sorted(parts, key=lambda p: int(p["metadata"].get("part_index", 0)))
        seen: set[str] = set()
        paragraphs: list[str] = []
        for part in ordered:
            for para in part["text"].split("\n\n"):
                key = para.strip()
                if key and key not in seen:
                    seen.add(key)
                    paragraphs.append(para)
        hit.text = "\n\n".join(paragraphs)
        return hit

    # ---------------------------------------------------------------------------- public

    def retrieve(
        self,
        query: str,
        *,
        k: int | None = None,
        similarity_floor: float | None = None,
        sentiment: str = "",
        category: str = "",
        product_area: str = "",
        inject_guaranteed: bool = True,
    ) -> RetrievalResult:
        k = self.k if k is None else k
        floor = self.similarity_floor if similarity_floor is None else similarity_floor

        # Over-fetch, because dedupe and the floor both remove candidates. Ask for enough
        # that a clause split into 2 parts cannot cost us a slot.
        raw = self.store.query(query, k=max(k * 3, k + 6))
        result = RetrievalResult(query=query)
        result.top_similarity = raw[0]["similarity"] if raw else 0.0

        best: dict[str, dict[str, Any]] = {}
        ordered_keys: list[str] = []
        for item in raw:
            pid = str(item["metadata"].get("policy_id", ""))
            key = pid if (pid and self.dedupe_by_policy_id) else item["chunk_id"]
            if key not in best:
                best[key] = item
                ordered_keys.append(key)
            elif _rank_score(item) > _rank_score(best[key]):
                best[key] = item  # keep the best-scoring part, keep original rank order

        kept: list[Hit] = []
        for key in ordered_keys:
            item = best[key]
            hit = self._to_hit(item)
            if hit.similarity is not None and hit.similarity < floor:
                result.rejected.append(hit)
                continue
            if (
                self.stitch_clause_parts
                and hit.policy_id
                and int(item["metadata"].get("part_count", 1)) > 1
            ):
                hit = self._stitch(hit, self.store.get_by_policy_ids([hit.policy_id]))
            kept.append(hit)
            if len(kept) >= k:
                break

        result.hits = kept

        # Guaranteed clauses are added on top of k, never in competition with it.
        if inject_guaranteed:
            wanted = resolve_guaranteed_policy_ids(
                self.routing_rules,
                sentiment=sentiment,
                category=category,
                product_area=product_area,
                known_policy_ids=self._known_policy_ids(),
            )
            already = {h.policy_id for h in result.hits if h.policy_id}
            missing = [pid for pid in wanted if pid not in already]
            by_pid: dict[str, list[dict[str, Any]]] = {}
            for raw_hit in self.store.get_by_policy_ids(missing):
                by_pid.setdefault(str(raw_hit["metadata"].get("policy_id", "")), []).append(
                    raw_hit
                )
            for pid in missing:
                parts = by_pid.get(pid) or []
                if not parts:
                    log.warning("guaranteed clause %s is not in the index", pid)
                    continue
                hit = self._to_hit(parts[0], injected=True)
                if len(parts) > 1 and self.stitch_clause_parts:
                    hit = self._stitch(hit, parts)
                result.hits.append(hit)

        return result


def build_index(engine: str = "hybrid") -> Any:
    """
    Assemble the search backend. All three options present the same interface, so `Retriever`
    does not know or care which it got.

    * `bm25`   -- lexical only. No torch, no Chroma, no built index. Scores doc recall@5 0.926
                  on its own, which makes it a usable fallback rather than just a test double.
    * `dense`  -- Chroma + sentence-transformers, the P1 slice.
    * `hybrid` -- both, fused by RRF. The default.
    """
    from src.utils.config import app_config, resolve

    cfg = app_config()
    ret_cfg = cfg["retrieval"]

    if engine == "bm25":
        from src.retrieval.bm25 import BM25Index

        return BM25Index.from_knowledge_base()

    from src.retrieval.vector_store import Embedder, KBVectorStore

    emb_cfg = ret_cfg["embedding"]
    store = KBVectorStore(
        resolve(cfg["paths"]["chroma_dir"]),
        collection_name=ret_cfg.get("collection_name", "northgate_kb"),
        embedder=Embedder(
            emb_cfg["model_name"],
            normalize=emb_cfg.get("normalize", True),
            query_prefix=emb_cfg.get("query_prefix", ""),
            batch_size=emb_cfg.get("batch_size", 32),
        ),
    )
    if store.count() == 0:
        raise RuntimeError(
            "the vector index is empty -- run `python scripts/build_index.py` first, "
            "or use engine='bm25' which needs no index"
        )
    if engine == "dense":
        return store

    from src.retrieval.bm25 import BM25Index
    from src.retrieval.hybrid import HybridIndex

    fusion = ret_cfg.get("fusion", {}) or {}
    return HybridIndex(
        store,
        BM25Index.from_knowledge_base(),
        candidate_pool=int(fusion.get("candidate_pool", 30)),
        rrf_k=int(fusion.get("rrf_k", 60)),
    )


def build_default_retriever(engine: str | None = None) -> Retriever:
    """Wire a retriever straight from the config files. Used by scripts and by the graph."""
    from src.utils.config import app_config, routing_rules

    cfg = app_config()
    ret_cfg = cfg["retrieval"]
    search = ret_cfg["search"]
    if engine is None:
        engine = "hybrid" if (ret_cfg.get("bm25", {}) or {}).get("enabled", True) else "dense"

    store = build_index(engine)
    return Retriever(
        store,
        k=search.get("k", 5),
        similarity_floor=search.get("similarity_floor", 0.35),
        dedupe_by_policy_id=search.get("dedupe_by_policy_id", True),
        stitch_clause_parts=search.get("stitch_clause_parts", True),
        routing_rules=routing_rules(),
    )
