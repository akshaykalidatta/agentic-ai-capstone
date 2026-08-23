"""
BM25 and hybrid fusion. Runs with nothing installed -- BM25 is pure standard library.

    python -m pytest tests/test_bm25.py -v
"""

from __future__ import annotations

import pytest

from src.retrieval.bm25 import BM25Index, tokenise
from src.retrieval.hybrid import HybridIndex


@pytest.fixture(scope="module")
def index():
    return BM25Index.from_knowledge_base()


# --------------------------------------------------------------------------- tokenisation


def test_clause_ids_survive_tokenisation():
    """The whole reason BM25 is here: `FEE-001` must stay a rare, matchable term."""
    assert "fee-001" in tokenise("Please reverse under FEE-001.")


def test_plurals_are_folded_but_real_words_are_not_mangled():
    assert tokenise("fees") == tokenise("fee")
    for word in ("class", "status", "analysis"):
        assert word in tokenise(word)


def test_stopwords_are_dropped_but_negation_is_kept():
    """A big stopword list would strip "not", and "must not contain" is meaningful here."""
    tokens = tokenise("the fee must not be waived")
    assert "the" not in tokens
    assert "not" in tokens


# ------------------------------------------------------------------------------- the index


def test_index_matches_the_dense_corpus(index):
    """84 chunks, 59 policy IDs -- the counts P1 fixed. Drift means the two halves disagree."""
    assert index.count() == 84
    assert len(index.all_policy_ids()) == 59


def test_an_exact_clause_id_query_ranks_that_clause_first(index):
    """
    Asking for FEE-001 is a lookup, not a search. BM25 alone gets it wrong -- TRB-002
    cross-references FEE-001 once and is shorter, so length normalisation floats the
    cross-reference above the clause. The fix is a metadata bonus, not term weighting.
    """
    for policy_id in ("FEE-001", "DSP-003", "CON-011"):
        assert index.query(policy_id, k=1)[0]["metadata"]["policy_id"] == policy_id
    assert index.query("what does CON-011 say", k=1)[0]["metadata"]["policy_id"] == "CON-011"


def test_clause_ids_are_not_split_into_family_plus_number():
    """Splitting FEE-001 into `fee` + `001` dilutes it against every clause in the family."""
    assert tokenise("FEE-001") == ["fee-001"]
    assert "sign" in tokenise("sign-in")  # ordinary hyphenated words still split


def test_section_tables_are_down_weighted(index):
    """
    The "decision quick reference" chunks are keyword grids that match every query. At full
    weight they outrank the deciding clause on most tickets -- measured doc@5 0.870 vs 0.926.
    """
    assert index.chunk_type_weights["section"] < index.chunk_type_weights["clause"]
    results = index.query("fraud on my account, multiple charges, card is with me", k=5)
    types = [r["metadata"]["chunk_type"] for r in results]
    assert types.count("section") <= 1


def test_scope_notes_stay_competitive(index):
    """
    Absence detection's second signal is a scope note out-ranking every clause. Damping scope
    to the same level as section improves doc recall and silently zeroes that signal.
    """
    assert index.chunk_type_weights["scope"] > index.chunk_type_weights["section"]
    results = index.query("mortgage escrow adjustment on my home loan", k=3)
    assert any(r["metadata"]["chunk_type"] == "scope" for r in results)


def test_query_results_have_the_store_interface_shape(index):
    """`Retriever` consumes these dicts directly; a missing key is a runtime AttributeError."""
    for result in index.query("overdraft fee", k=3):
        assert {"chunk_id", "text", "metadata", "similarity"} <= set(result)
        assert 0.0 <= result["similarity"] <= 1.0


def test_get_by_policy_ids_powers_guaranteed_injection(index):
    fetched = index.get_by_policy_ids(["CON-010", "CON-011"])
    assert {r["metadata"]["policy_id"] for r in fetched} == {"CON-010", "CON-011"}
    assert index.get_by_policy_ids([]) == []


def test_unmatched_query_returns_nothing_rather_than_noise(index):
    assert index.query("zzzz qqqq xxxx", k=5) == []


# ----------------------------------------------------------------------------------- gate


def test_bm25_alone_clears_the_p1_document_recall_gate(index):
    """
    0.921 at floor 0. Worth pinning: retrieval has a working fallback that needs no index,
    no torch and no API key.
    """
    from src.evaluation.retrieval_eval import evaluate
    from src.retrieval.retriever import Retriever
    from src.utils.config import routing_rules

    report = evaluate(
        Retriever(index, k=5, similarity_floor=0.0, routing_rules=routing_rules()), k=5
    )
    assert report.doc_recall >= 0.90  # measured 0.921
    assert report.doc_recall_hard >= 0.90  # measured 0.937
    assert report.false_absence_rate == 0.0


# --------------------------------------------------------------------------------- fusion


class FakeDenseStore:
    """Ranks by position in a fixed list, so fusion behaviour is exactly predictable."""

    def __init__(self, chunk_ids, corpus):
        self.chunk_ids = chunk_ids
        self.corpus = corpus

    def count(self):
        return len(self.corpus)

    def all_policy_ids(self):
        return set()

    def get_by_policy_ids(self, policy_ids):
        return []

    def query(self, query, k=5):
        return [
            {
                "chunk_id": cid,
                "text": self.corpus[cid],
                "metadata": {"policy_id": cid, "chunk_type": "clause", "citable": True},
                "similarity": round(0.9 - 0.05 * i, 3),
            }
            for i, cid in enumerate(self.chunk_ids[:k])
        ]


def test_rrf_promotes_a_chunk_both_lists_agree_on(index):
    """
    The point of fusion: something ranked mid-table by both beats something ranked first by
    one and absent from the other.
    """
    corpus = {f"c{i}": f"text {i}" for i in range(10)}
    dense = FakeDenseStore(["c9", "c8", "c7", "c1"], corpus)

    class FakeSparse(BM25Index):
        def __init__(self):
            pass

        chunk_type_weights = {}

        def count(self):
            return 10

        def query(self, query, k=5):
            return [
                {
                    "chunk_id": cid,
                    "text": corpus[cid],
                    "metadata": {"policy_id": cid, "chunk_type": "clause", "citable": True},
                    "similarity": 1.0,
                    "bm25_score": 5.0,
                }
                for cid in ["c5", "c4", "c1"][:k]
            ]

        def verify_matches(self, other_count):
            return None

    fused = HybridIndex(dense, FakeSparse(), candidate_pool=10).query("q", k=3)
    # c1 is 4th in dense and 3rd in sparse; nothing else appears in both.
    assert fused[0]["chunk_id"] == "c1"
    assert fused[0]["fused_score"] > fused[1]["fused_score"]


def test_bm25_only_hits_carry_no_dense_similarity(index):
    """
    `similarity=None` is what keeps absence detection honest: `below_floor` means "no dense
    hit survived the floor", and a lexical match must not silently satisfy it.
    """
    corpus = {"a": "alpha", "b": "beta"}
    dense = FakeDenseStore(["a"], corpus)

    class FakeSparse:
        def count(self):
            return 2

        def verify_matches(self, other_count):
            return None

        def query(self, query, k=5):
            return [
                {
                    "chunk_id": "b",
                    "text": "beta",
                    "metadata": {"policy_id": "b", "chunk_type": "clause", "citable": True},
                    "similarity": 1.0,
                    "bm25_score": 9.0,
                }
            ]

    fused = {r["chunk_id"]: r for r in HybridIndex(dense, FakeSparse()).query("q", k=5)}
    assert fused["a"]["similarity"] == 0.9  # dense cosine preserved
    assert fused["b"]["similarity"] is None  # lexical only
    assert fused["b"]["bm25_score"] == 9.0
