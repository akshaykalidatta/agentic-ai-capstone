"""
Clause-aware chunking (design decision D1).

The decision, restated
----------------------
We do **not** slide a fixed window over the policy text. One chunk = one policy clause.

Why it matters here specifically: FEE-001 grants a courtesy reversal *only if* four
conditions hold (fee < 60 days old, eligible fee type, account in good standing, no prior
reversal in 12 months). A 500-token window with a 50-token overlap will happily cut
between "A customer is eligible for one courtesy fee reversal" and condition 4. Retrieve
the first half and the model reads it as an unconditional entitlement -- and it will
promise the customer money. Groundedness becomes unmeasurable because the clause the
draft cites no longer contains the condition the draft ignored.

Three chunk types come out of this module
-----------------------------------------
`clause`  -- 59 of them, one per `### POLICY-ID`. The only citable kind.
`scope`   -- one per document, carrying the scope note. This is what makes *absence* of
             coverage retrievable: a mortgage-escrow question has no clause to match, but
             it does match "does not cover mortgage or home equity escrow adjustments".
`section` -- Definitions, published limits, quick-reference tables. Substantive text that
             is not a clause. Retrievable, not citable.

The token ceiling, and a correction to the HLD
----------------------------------------------
`docs/lld_notes.md` §3 guessed an 800-token ceiling. That number cannot work with our
embedding model: `BAAI/bge-small-en-v1.5` has `max_seq_length = 512`, and
sentence-transformers **silently truncates** anything longer. An 800-token chunk would be
indexed on its first 512 tokens and the rest would be invisible to retrieval -- with no
error to tell you. So the ceiling is 480 (512 minus room for the header we prepend), and
overflow clauses are split into overlapping parts that all keep the same `policy_id`.

The retriever then de-duplicates by `policy_id` and can stitch the parts back together,
so the *LLM* still sees the whole clause even though the *index* sees pieces of it. That
is the distinction to hold on to: what you embed and what you put in the prompt do not
have to be the same string.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.retrieval.document_loader import KBDocument

# A deliberately dependency-free token estimate, so this module (and its tests) run with
# nothing installed. English averages ~1.3 subword tokens per whitespace word for BERT-family
# tokenizers; policy text with tables and IDs runs a little higher, so we use 1.45 and treat
# the result as an upper bound. `scripts/build_index.py` passes the *real* tokenizer, and the
# build prints any place the two disagree by more than 15%.
def estimate_tokens(text: str) -> int:
    words = len(text.split())
    punctuation = len(re.findall(r"[|:;,.\-/()$%]", text))
    return int(words * 1.45 + punctuation * 0.25) + 2


@dataclass
class Chunk:
    """One unit that goes into the vector store."""

    chunk_id: str  # "refund_policy::FEE-001" (+ "#p2" when a clause overflowed)
    text: str  # what the LLM will read
    embed_text: str  # what we actually embed (header-prefixed)
    metadata: dict[str, Any]

    @property
    def policy_id(self) -> str:
        return self.metadata.get("policy_id", "")


@dataclass
class ChunkingConfig:
    max_tokens: int = 480
    overlap_tokens: int = 75
    embed_doc_title: bool = True
    embed_section_title: bool = True
    # LLD §3's guess was to prepend the whole scope note to every clause. Off by default:
    # it costs ~120 of our 480 tokens and makes all 7 FEE clauses look alike to the
    # embedder, hurting clause-level precision. The dedicated `scope` chunk already makes
    # absence retrievable. Flip this to True and re-run the eval if you want to test it --
    # that is exactly the kind of knob P1 exists to sweep.
    embed_scope_note: bool = False
    non_citable_policy_ids: tuple[str, ...] = ("CON-010",)


def _atoms(body: str, budget: int, count: Callable[[str], int]) -> list[str]:
    """
    Break a body into the smallest pieces we are willing to split between.

    Paragraphs first. A markdown table, though, is one paragraph with no blank lines in
    it -- and the decision quick-reference tables are the longest blocks in the KB. So any
    paragraph still over budget is broken again on single newlines (table rows, list items).
    """
    out: list[str] = []
    for para in (p for p in re.split(r"\n\s*\n", body) if p.strip()):
        if count(para) <= budget:
            out.append(para)
            continue
        rows, current = [], []
        for line in para.splitlines():
            if current and count("\n".join([*current, line])) > budget:
                rows.append("\n".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            rows.append("\n".join(current))
        out.extend(rows)
    return out


def _split_on_boundaries(
    body: str, cfg: ChunkingConfig, count: Callable[[str], int], header_tokens: int = 0
) -> list[str]:
    """
    Split an over-long body at structural boundaries, never mid-sentence.

    `header_tokens` is the cost of the doc-title / section / clause-heading prefix that
    `chunk_document` will prepend to every part. Ignore it and each part comes out over
    the model's 512-token window once the header is added -- which is precisely the silent
    truncation this ceiling exists to prevent.

    Overlap repeats whole trailing atoms rather than slicing a token window: a repeated
    half-sentence is noise in the embedding, a repeated numbered condition is not.
    """
    budget = max(cfg.max_tokens - header_tokens, 64)
    atoms = _atoms(body, budget, count)

    parts: list[list[str]] = []
    current: list[str] = []
    for atom in atoms:
        if current and count("\n\n".join([*current, atom])) > budget:
            parts.append(current)
            carry: list[str] = []
            for prev in reversed(current):
                if count("\n\n".join([prev, *carry])) > cfg.overlap_tokens:
                    break
                carry.insert(0, prev)
            current = [*carry, atom]
        else:
            current.append(atom)
    if current:
        parts.append(current)
    return ["\n\n".join(p) for p in parts] or [body]


def chunk_document(
    doc: KBDocument,
    cfg: ChunkingConfig | None = None,
    count_tokens: Callable[[str], int] | None = None,
) -> list[Chunk]:
    cfg = cfg or ChunkingConfig()
    count = count_tokens or estimate_tokens
    chunks: list[Chunk] = []

    base_meta = {
        "source_file": doc.source_file,
        "doc_id": doc.doc_id,
        "doc_title": doc.doc_title,
        "content_hash": doc.content_hash,
    }

    def header(section: str, clause_heading: str = "") -> str:
        bits: list[str] = []
        if cfg.embed_doc_title:
            bits.append(doc.doc_title)
        if cfg.embed_scope_note and doc.scope_note:
            bits.append(doc.scope_note)
        if cfg.embed_section_title and section:
            bits.append(section)
        if clause_heading:
            bits.append(clause_heading)
        return "\n".join(bits)

    # --- 1. the scope chunk: one per document, how absence becomes retrievable ---
    scope_text = f"{doc.doc_title}\nScope of this policy document.\n{doc.scope_note}"
    chunks.append(
        Chunk(
            chunk_id=f"{doc.stem}::scope",
            text=scope_text,
            embed_text=scope_text,
            metadata={
                **base_meta,
                "chunk_type": "scope",
                "policy_id": "",
                "family": "",
                "section": "Scope",
                "title": "Scope note",
                "citable": False,
                "part_index": 0,
                "part_count": 1,
            },
        )
    )

    # --- 2. clause chunks: the 59 citable units ---
    for clause in doc.clauses:
        head = header(clause.section, clause.heading)
        body_parts = (
            [clause.body]
            if count(f"{head}\n{clause.body}") <= cfg.max_tokens
            else _split_on_boundaries(clause.body, cfg, count, count(head))
        )
        for idx, part in enumerate(body_parts):
            suffix = "" if len(body_parts) == 1 else f"#p{idx + 1}"
            chunks.append(
                Chunk(
                    chunk_id=f"{doc.stem}::{clause.policy_id}{suffix}",
                    text=f"{clause.heading}\n{part}",
                    embed_text=f"{head}\n{part}",
                    metadata={
                        **base_meta,
                        "chunk_type": "clause",
                        "policy_id": clause.policy_id,
                        "family": clause.family,
                        "section": clause.section,
                        "title": clause.title,
                        "citable": clause.policy_id not in cfg.non_citable_policy_ids,
                        "part_index": idx,
                        "part_count": len(body_parts),
                    },
                )
            )

    # --- 3. section chunks: tables and definitions, retrievable but never cited ---
    for section in doc.sections:
        slug = re.sub(r"[^a-z0-9]+", "-", section.title.lower()).strip("-")[:40]
        head = header(section.title)
        body_parts = (
            [section.body]
            if count(f"{head}\n{section.body}") <= cfg.max_tokens
            else _split_on_boundaries(section.body, cfg, count, count(head))
        )
        for idx, part in enumerate(body_parts):
            suffix = "" if len(body_parts) == 1 else f"#p{idx + 1}"
            chunks.append(
                Chunk(
                    chunk_id=f"{doc.stem}::sec-{slug}{suffix}",
                    text=f"{section.title}\n{part}",
                    embed_text=f"{header(section.title)}\n{part}",
                    metadata={
                        **base_meta,
                        "chunk_type": "section",
                        "policy_id": "",
                        "family": "",
                        "section": section.title,
                        "title": section.title,
                        "citable": False,
                        "part_index": idx,
                        "part_count": len(body_parts),
                    },
                )
            )

    for chunk in chunks:
        chunk.metadata["token_estimate"] = count(chunk.embed_text)
    return chunks


def chunk_all(
    docs: list[KBDocument],
    cfg: ChunkingConfig | None = None,
    count_tokens: Callable[[str], int] | None = None,
) -> list[Chunk]:
    out: list[Chunk] = []
    for doc in docs:
        out.extend(chunk_document(doc, cfg, count_tokens))

    ids = [c.chunk_id for c in out]
    if len(ids) != len(set(ids)):
        dupes = {i for i in ids if ids.count(i) > 1}
        raise ValueError(f"duplicate chunk_ids -- indexing would silently drop one: {dupes}")
    return out
