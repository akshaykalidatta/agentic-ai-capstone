"""
Load the knowledge-base markdown files into structured `KBDocument` objects.

Why this module exists at all
----------------------------
A naive RAG pipeline does `open(f).read()` and hands the whole string to a splitter.
That throws away every piece of structure the policy authors deliberately put in the
file: the document ID, the scope note that says what the document does *not* cover,
and the `### FEE-001 — ...` clause headings that are the unit a compliance reviewer
actually cites.

We keep all of it, because downstream phases need it:

* `policy_id`   -> the citation the drafting node is allowed to quote (P4)
* `scope_note`  -> how "no policy covers this" becomes *retrievable* (the 8 no-policy tickets)
* `content_hash`-> lets the indexer skip files that have not changed (the KB is hand-edited)

This module does no chunking and no embedding. It only parses. Keeping parse / chunk /
embed as three separate steps means you can unit-test the parser with zero dependencies
installed, which is exactly what we do in `tests/test_chunking.py`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

# `### FEE-001 — One-time courtesy reversal`  ->  ("FEE-001", "One-time courtesy reversal")
# The dash in the KB is an em dash (U+2014). We accept an ASCII hyphen too, so a
# hand-edit that loses the em dash does not silently drop a clause from the index.
CLAUSE_HEADING = re.compile(r"^###\s+([A-Z]{2,4}-\d{2,4})\s*[—–-]\s*(.+?)\s*$")
SECTION_HEADING = re.compile(r"^##\s+(.+?)\s*$")
OTHER_H3 = re.compile(r"^###\s+(.+?)\s*$")
DOC_TITLE = re.compile(r"^#\s+(.+?)\s*$")
FRONT_MATTER = re.compile(r"^\*\*(.+?):\*\*\s*(.*)$")


@dataclass
class Clause:
    """One `### POLICY-ID — Title` block: the atomic unit of policy."""

    policy_id: str
    title: str
    body: str
    section: str  # the enclosing `## ` heading, e.g. "2. Fee reversals (FEE)"

    @property
    def family(self) -> str:
        """`FEE-001` -> `FEE`. Used for the guaranteed-context rules (all `CON-*`)."""
        return self.policy_id.split("-")[0]

    @property
    def heading(self) -> str:
        return f"### {self.policy_id} — {self.title}"


@dataclass
class Section:
    """
    A `## ` block that carries substantive text but is *not* a citable clause:
    Definitions tables, "Published limits", the decision quick-reference tables.

    These get indexed too. A ticket asking "what's the Zelle daily limit" is answered
    by the limits table, not by any TRB clause -- if we only indexed clauses, that
    retrieval would miss.
    """

    title: str
    body: str


@dataclass
class KBDocument:
    source_file: str  # "refund_policy.md" -- matches golden `expected_kb_sources`
    doc_title: str
    doc_id: str  # "KB-REF-2026-03"
    front_matter: dict[str, str]
    scope_note: str
    clauses: list[Clause] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    content_hash: str = ""

    @property
    def stem(self) -> str:
        return self.source_file.removesuffix(".md")


def _clean(lines: list[str]) -> str:
    """Drop `---` rules and collapse the blank lines they leave behind."""
    kept = [ln for ln in lines if ln.strip() != "---"]
    text = "\n".join(kept).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def parse_markdown(text: str, source_file: str) -> KBDocument:
    """Parse one KB file. Pure function over a string -- trivially testable."""
    lines = text.splitlines()

    doc_title = ""
    front_matter: dict[str, str] = {}
    scope_lines: list[str] = []
    body_start = 0

    # --- header: title, `**Key:** value` front matter, then the first blockquote ---
    seen_blockquote = False
    for i, line in enumerate(lines):
        if not doc_title and (m := DOC_TITLE.match(line)):
            doc_title = m.group(1)
            continue
        if m := FRONT_MATTER.match(line):
            front_matter[m.group(1)] = m.group(2)
            continue
        if line.startswith(">"):
            seen_blockquote = True
            scope_lines.append(line.lstrip(">").strip())
            continue
        if seen_blockquote and line.strip() and not line.startswith(">"):
            # first non-blockquote content line after the scope note: body starts here
            body_start = i
            break
    else:
        body_start = len(lines)

    scope_note = re.sub(r"\n{2,}", "\n", "\n".join(scope_lines)).strip()
    scope_note = re.sub(r"\*\*(.+?)\*\*", r"\1", scope_note)  # de-bold for embedding

    doc = KBDocument(
        source_file=source_file,
        doc_title=doc_title,
        doc_id=front_matter.get("Document ID", ""),
        front_matter=front_matter,
        scope_note=scope_note,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
    )

    # --- body: walk the lines, accumulating into the current clause / section ---
    current_section = ""
    section_preamble: list[str] = []  # text under a `##` before its first `###`
    clause: Clause | None = None
    clause_lines: list[str] = []
    non_clause_h3: str | None = None  # a `###` that is not a policy clause

    def flush_clause() -> None:
        nonlocal clause, clause_lines
        if clause is not None:
            clause.body = _clean(clause_lines)
            doc.clauses.append(clause)
        clause, clause_lines = None, []

    def flush_section() -> None:
        nonlocal section_preamble, non_clause_h3
        body = _clean(section_preamble)
        # Only index a section if it actually carries content of its own. A `##` that is
        # nothing but a container for clauses ("## 2. Fee reversals (FEE)") has none.
        if current_section and len(body) > 60:
            doc.sections.append(Section(title=current_section, body=body))
        section_preamble, non_clause_h3 = [], None

    for line in lines[body_start:]:
        if m := SECTION_HEADING.match(line):
            flush_clause()
            flush_section()
            current_section = m.group(1)
            continue
        if m := CLAUSE_HEADING.match(line):
            flush_clause()
            non_clause_h3 = None
            clause = Clause(
                policy_id=m.group(1), title=m.group(2), body="", section=current_section
            )
            continue
        if m := OTHER_H3.match(line):
            # A non-clause `###` (none today, but a hand-edit could add one). Fold its
            # text into the enclosing section rather than dropping it on the floor.
            flush_clause()
            non_clause_h3 = m.group(1)
            section_preamble.append(f"{non_clause_h3}:")
            continue

        if clause is not None:
            clause_lines.append(line)
        else:
            section_preamble.append(line)

    flush_clause()
    flush_section()
    return doc


def load_kb(kb_dir: str | Path) -> list[KBDocument]:
    """Parse every `*.md` in the knowledge-base directory, sorted for reproducibility."""
    kb_path = Path(kb_dir)
    if not kb_path.is_dir():
        raise FileNotFoundError(f"knowledge base directory not found: {kb_path}")

    docs: list[KBDocument] = []
    for path in sorted(kb_path.glob("*.md")):
        docs.append(parse_markdown(path.read_text(encoding="utf-8"), path.name))
    if not docs:
        raise ValueError(f"no markdown files found in {kb_path}")
    return docs
