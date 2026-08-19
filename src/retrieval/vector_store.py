"""
Embedding + Chroma persistence.

Two things in this file are easy to get wrong and expensive to debug later, so they are
called out where they happen:

1. **Chroma's default distance is L2, not cosine.** Every threshold in this project
   (`similarity_floor: 0.35`) is a *cosine similarity*. If the collection is created with
   the default space, `1 - distance` is not a similarity and the floor silently means
   nothing. We force `cosine` at creation time and assert it on every open.

2. **bge-v1.5 is asymmetric.** It was trained so that queries carry an instruction prefix
   and passages do not. Embedding both sides the same way still "works" -- it just quietly
   costs recall. Hence `embed_query` and `embed_documents` are different methods.

The heavy imports (`chromadb`, `sentence_transformers`) happen inside `__init__`, not at
module import, so `tests/test_chunking.py` can import the retrieval package with nothing
installed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from src.retrieval.chunking import Chunk

log = logging.getLogger(__name__)


class Embedder:
    """Local sentence-transformers embedder. Loaded once, reused for the whole run."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        *,
        normalize: bool = True,
        query_prefix: str = "",
        batch_size: int = 32,
    ) -> None:
        from sentence_transformers import SentenceTransformer  # heavy: import lazily

        self.model_name = model_name
        self.normalize = normalize
        self.query_prefix = query_prefix
        self.batch_size = batch_size
        self.model = SentenceTransformer(model_name)
        # 512 for bge-small. The chunker's ceiling must stay under this or the tail of a
        # chunk is dropped with no warning at all.
        self.max_seq_length = int(getattr(self.model, "max_seq_length", 512))
        log.info(
            "loaded %s (dim=%d, max_seq_length=%d)",
            model_name,
            self.model.get_sentence_embedding_dimension(),
            self.max_seq_length,
        )

    def count_tokens(self, text: str) -> int:
        """Real tokenizer count -- what the model will actually see."""
        return len(self.model.tokenizer.encode(text, add_special_tokens=True))

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self.model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=self.normalize,
            show_progress_bar=len(texts) > 64,
        )
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        vector = self.model.encode(
            f"{self.query_prefix}{text}",
            normalize_embeddings=self.normalize,
            show_progress_bar=False,
        )
        return vector.tolist()


class KBVectorStore:
    """Persistent Chroma collection holding the chunked knowledge base."""

    def __init__(
        self,
        persist_dir: str | Path,
        collection_name: str = "northgate_kb",
        embedder: Embedder | None = None,
    ) -> None:
        import chromadb  # heavy: import lazily

        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.embedder = embedder
        self.client = chromadb.PersistentClient(path=str(self.persist_dir))
        self.collection = self._open_collection()

    # ---------------------------------------------------------------- collection setup

    def _open_collection(self) -> Any:
        """
        Open (or create) the collection with cosine distance.

        Chroma moved this setting from `metadata={"hnsw:space": ...}` to
        `configuration={"hnsw": {"space": ...}}` between major versions, so we try the
        newer form and fall back. Both are accepted by the versions in requirements.txt.
        """
        kwargs: dict[str, Any] = {"name": self.collection_name, "embedding_function": None}
        try:
            collection = self.client.get_or_create_collection(
                **kwargs, configuration={"hnsw": {"space": "cosine"}}
            )
        except TypeError:
            collection = self.client.get_or_create_collection(
                **kwargs, metadata={"hnsw:space": "cosine"}
            )

        space = self._collection_space(collection)
        if space not in (None, "cosine"):
            raise RuntimeError(
                f"collection '{self.collection_name}' uses distance space '{space}', not "
                f"cosine. Every threshold in config assumes cosine similarity. Delete "
                f"{self.persist_dir} and rebuild."
            )
        return collection

    @staticmethod
    def _collection_space(collection: Any) -> str | None:
        meta = collection.metadata or {}
        if "hnsw:space" in meta:
            return str(meta["hnsw:space"])
        config = getattr(collection, "configuration_json", None) or {}
        hnsw = config.get("hnsw") or {}
        return hnsw.get("space")

    # -------------------------------------------------------------------------- writing

    def indexed_hashes(self) -> dict[str, str]:
        """`{source_file: content_hash}` for what is already in the index."""
        existing = self.collection.get(include=["metadatas"])
        out: dict[str, str] = {}
        for meta in existing.get("metadatas") or []:
            if meta and (src := meta.get("source_file")):
                out[str(src)] = str(meta.get("content_hash", ""))
        return out

    def delete_source(self, source_file: str) -> None:
        self.collection.delete(where={"source_file": source_file})

    def upsert(self, chunks: Sequence[Chunk]) -> int:
        """Embed and write the given chunks. Returns how many were written."""
        if not chunks:
            return 0
        if self.embedder is None:
            raise RuntimeError("KBVectorStore needs an Embedder to write")

        embeddings = self.embedder.embed_documents([c.embed_text for c in chunks])
        self.collection.upsert(
            ids=[c.chunk_id for c in chunks],
            documents=[c.text for c in chunks],
            embeddings=embeddings,
            metadatas=[dict(c.metadata) for c in chunks],
        )
        return len(chunks)

    def count(self) -> int:
        return self.collection.count()

    # -------------------------------------------------------------------------- reading

    def query(
        self, query_text: str, k: int = 5, where: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """
        Dense search. Returns dicts with a **cosine similarity**, not a distance.

        Chroma reports `distance = 1 - cosine_similarity` in cosine space, so we invert it
        here, once, rather than leaving every caller to remember which direction is better.
        """
        if self.embedder is None:
            raise RuntimeError("KBVectorStore needs an Embedder to query")

        result = self.collection.query(
            query_embeddings=[self.embedder.embed_query(query_text)],
            n_results=k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        hits: list[dict[str, Any]] = []
        for cid, doc, meta, dist in zip(
            result["ids"][0],
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
            strict=True,
        ):
            hits.append(
                {
                    "chunk_id": cid,
                    "text": doc,
                    "metadata": dict(meta or {}),
                    "similarity": round(1.0 - float(dist), 4),
                }
            )
        return hits

    def get_by_policy_ids(self, policy_ids: Sequence[str]) -> list[dict[str, Any]]:
        """Fetch clause chunks by policy ID -- used for guaranteed context injection."""
        ids = list(dict.fromkeys(policy_ids))
        if not ids:
            return []
        where = {"policy_id": {"$in": ids}} if len(ids) > 1 else {"policy_id": ids[0]}
        got = self.collection.get(where=where, include=["documents", "metadatas"])
        return [
            {"chunk_id": cid, "text": doc, "metadata": dict(meta or {}), "similarity": None}
            for cid, doc, meta in zip(
                got.get("ids") or [], got.get("documents") or [], got.get("metadatas") or []
            )
        ]

    def all_policy_ids(self) -> set[str]:
        got = self.collection.get(include=["metadatas"])
        return {
            str(m["policy_id"])
            for m in (got.get("metadatas") or [])
            if m and m.get("policy_id")
        }
