"""
Lexical (BM25) search over the same 84 chunks the vector store holds.

Dense embeddings blur exact tokens. `FEE-001` and `FEE-006` land in almost the same place in
vector space, and a ticket quoting a clause ID by name gets no benefit from having done so.
BM25 treats that ID as a rare term and ranks it first. That is the whole reason for this file.

It deliberately implements the **same interface as `KBVectorStore`** -- `query`,
`get_by_policy_ids`, `all_policy_ids`, `count` -- so it can be dropped into `Retriever`
unchanged, either on its own (no torch, no Chroma, no index) or behind `HybridIndex`.

Pure standard library. That is not asceticism: it means retrieval can be evaluated on a
machine with nothing installed, which is how P1's floor was measured before the model existed.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# Okapi BM25 defaults. k1 controls term-frequency saturation, b the length normalisation.
# Standard values; the corpus is 84 short documents, so there is little to gain from tuning.
BM25_K1 = 1.5
BM25_B = 0.75

# Per-chunk-type score multipliers, and the most important thing in this file.
#
# The 19 `section` chunks are "decision quick reference" tables -- dense grids of scenario
# keywords. To BM25 they look like a document about everything, so they outrank the clause
# that actually decides the ticket. Measured on the 99 golden tickets with a policy:
#
#     section 1.0, scope 1.0   doc@5 0.870   clause 0.606   scope signal 0.625
#     section 0.3, scope 0.6   doc@5 0.926   clause 0.690   scope signal 0.625
#     section 0.3, scope 0.3   doc@5 0.926   clause 0.690   scope signal 0.000  <-- trap
#
# The two weights have to move independently. Damping both together reads as an improvement
# on the headline number and silently destroys absence detection, because signal 2 for "no
# policy covers this" *is* a scope chunk out-ranking every clause. Down-weight the tables,
# leave the scope notes competitive.
#
# This also answers `lld_p1_retrieval.md` §10 question 4 for the lexical half: the section
# chunks do not earn a full-weight place, but they are worth keeping at a discount.
CHUNK_TYPE_WEIGHTS: dict[str, float] = {"clause": 1.0, "section": 0.3, "scope": 0.6}

# Small and deliberate. A big stopword list would strip "not", and "must not contain" is a
# meaningful phrase in a policy corpus.
STOPWORDS = frozenset(
    """a an and are as at be by for from has have how i if in is it its of on or that the
    this to was were what when where which will with you your""".split()
)

# Keeps `fee-001` and `reg-e` whole rather than shattering them on the hyphen.
TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

# A clause identifier: three letters, a hyphen, three digits.
POLICY_ID_PATTERN = re.compile(r"^[a-z]{3}-\d{3}$")

# Bonus added to a chunk whose OWN policy_id the query named. Asking for "FEE-001" is a
# lookup, not a search, and BM25 alone gets it wrong: TRB-002 cross-references FEE-001 once
# and is shorter, so length normalisation puts the cross-reference above the clause itself.
# No amount of term weighting fixes that, because the text really does say what BM25 thinks
# it says -- the missing signal is metadata, not words.
POLICY_ID_EXACT_MATCH_BONUS = 10.0


def _singularise(token: str) -> str:
    """
    Crude but safe plural stripping: `fees` -> `fee`, while leaving `class`, `status`,
    `analysis` alone. A real stemmer would be better and would add a dependency for a corpus
    of 84 documents.
    """
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def tokenise(text: str) -> list[str]:
    """
    Lowercase, split, drop stopwords, singularise.

    Hyphenated tokens are emitted **three** ways: whole (`fee-001`), as parts (`fee`, `001`)
    and concatenated (`fee001`). The whole form is what makes an exact clause-ID match score
    highly; the parts keep a ticket that says "fee 001" or "FEE001" findable. Cheap
    over-generation beats a missed exact match here.
    """
    tokens: list[str] = []
    for match in TOKEN_PATTERN.findall(text.lower()):
        if POLICY_ID_PATTERN.match(match):
            # An identifier, not a phrase. Splitting it into `fee` + `001` dilutes the exact
            # match against every clause in the FEE family, which is the opposite of the point.
            tokens.append(match)
        elif "-" in match:
            tokens.append(match)
            parts = [p for p in match.split("-") if p]
            tokens.extend(parts)
            tokens.append("".join(parts))
        else:
            tokens.append(match)
    return [_singularise(t) for t in tokens if t not in STOPWORDS and len(t) > 1]


@dataclass
class BM25Document:
    chunk_id: str
    text: str  # what the LLM reads
    index_text: str  # what gets tokenised
    metadata: dict[str, Any]
    tokens: list[str] = field(default_factory=list)
    term_frequencies: Counter = field(default_factory=Counter)


class BM25Index:
    """
    An in-memory BM25 index. Built in ~10 ms over 84 chunks, so it is rebuilt on startup
    rather than persisted -- there is no cache-invalidation problem if there is no cache.
    """

    mode = "bm25"

    def __init__(
        self, documents: list[BM25Document], *, chunk_type_weights: dict[str, float] | None = None
    ) -> None:
        self.documents = documents
        self.chunk_type_weights = dict(chunk_type_weights or CHUNK_TYPE_WEIGHTS)
        for document in self.documents:
            document.tokens = tokenise(document.index_text)
            document.term_frequencies = Counter(document.tokens)

        self.document_count = len(documents)
        self.average_length = (
            sum(len(d.tokens) for d in documents) / self.document_count
            if self.document_count
            else 0.0
        )

        document_frequency: Counter = Counter()
        for document in documents:
            document_frequency.update(set(document.tokens))

        # Precomputed so scoring a query is a dict lookup per term, not a corpus scan.
        self.inverse_document_frequency = {
            term: math.log(1 + (self.document_count - freq + 0.5) / (freq + 0.5))
            for term, freq in document_frequency.items()
        }

    # ------------------------------------------------------------------------ construction

    @classmethod
    def from_chunks(
        cls, chunks: list[Any], *, chunk_type_weights: dict[str, float] | None = None
    ) -> BM25Index:
        """Build from `chunking.Chunk` objects -- the same list that is embedded."""
        return cls(
            [
                BM25Document(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    # `embed_text` carries the doc title and section heading, which are strong
                    # lexical signals ("refund policy", "fee reversals") that the bare clause
                    # body does not contain.
                    index_text=chunk.embed_text,
                    metadata=dict(chunk.metadata),
                )
                for chunk in chunks
            ],
            chunk_type_weights=chunk_type_weights,
        )

    @classmethod
    def from_knowledge_base(cls, path: Any = None) -> BM25Index:
        """
        Build straight from `data/knowledge_base/*.md`. No Chroma, no embedding model.

        The markdown is the source of truth and chunking is deterministic, so this produces
        exactly the chunk set the vector store holds -- `verify_matches` checks that claim
        rather than assuming it.
        """
        from src.retrieval.chunking import ChunkingConfig, chunk_all
        from src.retrieval.document_loader import load_kb
        from src.utils.config import app_config, resolve

        config = app_config()
        kb_path = path or resolve(config["paths"]["knowledge_base"])
        chunking_config = ChunkingConfig(**dict(config["retrieval"]["chunking"]))
        weights = (config["retrieval"].get("bm25", {}) or {}).get("chunk_type_weights")
        return cls.from_chunks(
            chunk_all(load_kb(kb_path), chunking_config), chunk_type_weights=weights
        )

    def verify_matches(self, other_count: int) -> None:
        """
        Warn if the lexical and dense corpora have drifted apart.

        They can: the index is a build artefact and the markdown is hand-edited, so editing a
        policy without re-running `build_index.py` leaves Chroma stale while BM25 is current.
        Fusing two different corpora produces plausible nonsense, so it is worth a loud line.
        """
        if other_count and other_count != self.count():
            log.warning(
                "BM25 has %d chunks but the vector store has %d -- re-run "
                "scripts/build_index.py; hybrid results will be inconsistent until you do",
                self.count(),
                other_count,
            )

    # -------------------------------------------------------- KBVectorStore-compatible API

    def count(self) -> int:
        return self.document_count

    def all_policy_ids(self) -> set[str]:
        return {
            str(d.metadata.get("policy_id", "")) for d in self.documents if d.metadata.get("policy_id")
        }

    def get_by_policy_ids(self, policy_ids: list[str]) -> list[dict[str, Any]]:
        wanted = set(policy_ids)
        if not wanted:
            return []
        return [
            self._as_result(document, similarity=None)
            for document in self.documents
            if document.metadata.get("policy_id") in wanted
        ]

    def query(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """
        Top-k by BM25, in the shape `Retriever` expects.

        `similarity` is the raw score divided by the best score in *this* result set, so it
        lands in 0..1 and the retriever's floor still filters something sensible when BM25 is
        used alone. It is a rank proxy, **not** a cosine -- do not read a BM25-only run's
        `top_similarity` as comparable to a dense one's.
        """
        scores = self.score_all(query)
        if not scores:
            return []
        best = scores[0][1] or 1.0
        return [
            self._as_result(self.documents[i], similarity=round(score / best, 4), bm25=score)
            for i, score in scores[:k]
        ]

    # ---------------------------------------------------------------------------- scoring

    def score_all(self, query: str) -> list[tuple[int, float]]:
        """`(document index, score)` for every document that matched, best first."""
        query_terms = tokenise(query)
        if not query_terms:
            return []
        named_policy_ids = {t.upper() for t in query_terms if POLICY_ID_PATTERN.match(t)}

        scores: dict[int, float] = {}
        for index, document in enumerate(self.documents):
            length = len(document.tokens) or 1
            total = 0.0
            for term in query_terms:
                frequency = document.term_frequencies.get(term)
                if not frequency:
                    continue
                idf = self.inverse_document_frequency.get(term, 0.0)
                denominator = frequency + BM25_K1 * (
                    1 - BM25_B + BM25_B * length / (self.average_length or 1)
                )
                total += idf * frequency * (BM25_K1 + 1) / denominator
            weight = self.chunk_type_weights.get(str(document.metadata.get("chunk_type", "")), 1.0)
            total *= weight
            if named_policy_ids and document.metadata.get("policy_id") in named_policy_ids:
                total += POLICY_ID_EXACT_MATCH_BONUS
            if total > 0:
                scores[index] = total

        return sorted(scores.items(), key=lambda pair: (-pair[1], self.documents[pair[0]].chunk_id))

    def _as_result(
        self, document: BM25Document, *, similarity: float | None, bm25: float | None = None
    ) -> dict[str, Any]:
        return {
            "chunk_id": document.chunk_id,
            "text": document.text,
            "metadata": document.metadata,
            "similarity": similarity,
            "bm25_score": round(bm25, 4) if bm25 is not None else None,
        }
