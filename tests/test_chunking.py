"""
Tests for the parse + chunk stage. These run with **no dependencies installed** -- no
chromadb, no torch, no model download -- which is why parsing and embedding are separate
modules. Fast tests you can run on every edit are worth designing for.

    python -m pytest tests/test_chunking.py -q
    python tests/test_chunking.py            # also works, no pytest needed
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.retrieval.chunking import ChunkingConfig, chunk_all, estimate_tokens  # noqa: E402
from src.retrieval.document_loader import load_kb, parse_markdown  # noqa: E402
from src.utils.config import app_config, resolve  # noqa: E402

EXPECTED_CLAUSES = 59
KB_DIR = resolve(app_config()["paths"]["knowledge_base"])

SAMPLE = """# Test Policy

**Document ID:** KB-TST-2026-01
**Owner:** Nobody

> **Scope note.** Covers widgets. Does **not** cover gadgets.

---

## 1. Definitions

| Term | Definition |
| --- | --- |
| Widget | A thing that is a widget and needs enough words here to clear the sixty
character floor that the section chunker applies. |

---

## 2. Widgets (WID)

### WID-001 — Widget replacement
A widget may be replaced when all of the following are true:

1. It is broken.
2. It is under warranty.

### WID-002 — Widget refunds
No refunds on widgets.
"""


def test_parse_header_and_scope() -> None:
    doc = parse_markdown(SAMPLE, "test_policy.md")
    assert doc.doc_title == "Test Policy"
    assert doc.doc_id == "KB-TST-2026-01"
    assert "Covers widgets" in doc.scope_note
    assert "does not cover gadgets" in doc.scope_note.lower()  # bold markers stripped
    assert doc.content_hash


def test_parse_clauses_and_sections() -> None:
    doc = parse_markdown(SAMPLE, "test_policy.md")
    assert [c.policy_id for c in doc.clauses] == ["WID-001", "WID-002"]
    assert doc.clauses[0].title == "Widget replacement"
    assert doc.clauses[0].section == "2. Widgets (WID)"
    assert doc.clauses[0].family == "WID"
    # the conditions must stay attached to the clause that grants the entitlement --
    # this assertion is design decision D1 in executable form
    assert "under warranty" in doc.clauses[0].body
    assert [s.title for s in doc.sections] == ["1. Definitions"]


def test_chunk_types_and_ids() -> None:
    doc = parse_markdown(SAMPLE, "test_policy.md")
    chunks = chunk_all([doc])
    ids = {c.chunk_id for c in chunks}
    assert "test_policy::scope" in ids
    assert "test_policy::WID-001" in ids
    clause = next(c for c in chunks if c.chunk_id == "test_policy::WID-001")
    assert clause.metadata["chunk_type"] == "clause"
    assert clause.metadata["citable"] is True
    # the embedded text carries the header; the LLM text does not need the doc title
    assert clause.embed_text.startswith("Test Policy")
    assert clause.text.startswith("### WID-001")


def test_non_citable_flag() -> None:
    doc = parse_markdown(SAMPLE, "test_policy.md")
    cfg = ChunkingConfig(non_citable_policy_ids=("WID-002",))
    chunks = chunk_all([doc], cfg)
    flags = {c.policy_id: c.metadata["citable"] for c in chunks if c.policy_id}
    assert flags == {"WID-001": True, "WID-002": False}


def test_overflow_splits_and_keeps_policy_id() -> None:
    doc = parse_markdown(SAMPLE, "test_policy.md")
    chunks = chunk_all([doc], ChunkingConfig(max_tokens=70, overlap_tokens=10))
    parts = [c for c in chunks if c.policy_id == "WID-001"]
    assert len(parts) >= 1
    assert all(c.metadata["policy_id"] == "WID-001" for c in parts)
    assert {c.metadata["part_index"] for c in parts} == set(range(len(parts)))


def test_real_kb_has_all_59_clauses() -> None:
    """The number that must never drift silently."""
    docs = load_kb(KB_DIR)
    chunks = chunk_all(docs)
    policy_ids = {c.policy_id for c in chunks if c.policy_id}
    assert len(policy_ids) == EXPECTED_CLAUSES, sorted(policy_ids)
    assert {c.metadata["chunk_type"] for c in chunks} == {"clause", "scope", "section"}
    # one scope chunk per document, so "not covered" is always retrievable
    assert sum(1 for c in chunks if c.metadata["chunk_type"] == "scope") == len(docs)


def test_no_chunk_exceeds_the_embedding_window() -> None:
    """
    bge-small truncates at 512 tokens without warning. A chunk over the ceiling would be
    indexed on its prefix only, and nothing would tell us. Guard it.
    """
    cfg = app_config()["retrieval"]["chunking"]
    ceiling = cfg["max_tokens"]
    assert ceiling <= 512, "ceiling must stay inside bge-small's 512-token window"
    chunks = chunk_all(load_kb(KB_DIR), ChunkingConfig(max_tokens=ceiling))
    over = [(c.chunk_id, estimate_tokens(c.embed_text)) for c in chunks
            if estimate_tokens(c.embed_text) > ceiling]
    assert not over, over


def test_chunk_ids_are_unique() -> None:
    chunks = chunk_all(load_kb(KB_DIR))
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok    {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL  {name}: {exc}")
    print(f"\n{failures} failure(s)")
    raise SystemExit(1 if failures else 0)
