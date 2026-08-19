# P1 code walkthrough — how to read what was just built

A reading guide, not documentation. Roughly 45 minutes if you follow the order below with the
files open beside you. The design *reasoning* is in `docs/lld_p1_retrieval.md`; this document is
about the code itself — what each function does, why each non-obvious line is there, and which
Python techniques are worth stealing for the phases ahead.

---

## 0. Read in this order

| # | File | Lines | Why here |
| --- | --- | --- | --- |
| 1 | `src/utils/config.py` | ~35 | Smallest file in the project. Establishes how every other file finds things. |
| 2 | `src/retrieval/document_loader.py` | ~200 | Pure text in, structured objects out. No dependencies, no cleverness. |
| 3 | `src/retrieval/chunking.py` | ~230 | Structured objects in, index-ready chunks out. Where design decision D1 actually lives. |
| 4 | `tests/test_chunking.py` | ~140 | Read the tests *before* the harder modules. Tests are the spec, written in the shortest possible form. |
| 5 | `src/retrieval/vector_store.py` | ~230 | First file with external dependencies. Embeddings and Chroma. |
| 6 | `src/retrieval/query_builder.py` | ~110 | Short, and the highest-leverage file in the phase. |
| 7 | `src/retrieval/retriever.py` | ~290 | Composes everything above into the one object the graph will call. |
| 8 | `src/evaluation/retrieval_eval.py` | ~300 | How we know any of it works. |
| 9 | `scripts/build_index.py`, `scripts/query_kb.py` | ~180, ~100 | Thin command-line skins over the modules. Nothing new, just wiring. |

The order is deliberately **dependency order**: each file only imports things you have already
read. If you jump straight to `retriever.py` you will spend the whole time chasing definitions.

---

## 1. The shape of the whole thing

Two pipelines. The first runs once, offline. The second runs once per ticket.

```
BUILD  (scripts/build_index.py)
  data/knowledge_base/*.md
    │  load_kb()                      document_loader.py
    ▼  5 × KBDocument  { doc_title, doc_id, scope_note, clauses[], sections[], content_hash }
    │  chunk_all()                    chunking.py
    ▼  84 × Chunk      { chunk_id, text, embed_text, metadata{} }
    │  Embedder.embed_documents()     vector_store.py
    ▼  84 × 384-dim vector
    │  KBVectorStore.upsert()
    ▼  .chroma/                       persistent, cosine space

SEARCH (Retriever.retrieve, called by the future graph node)
  ticket dict
    │  from_ticket() / build_query()  query_builder.py
    ▼  "Fee from March. checking. i'm going through my statements..."
    │  Embedder.embed_query()         (note: query prefix added here, not for documents)
    ▼  1 × 384-dim vector
    │  chroma.query(n_results = k*3)  over-fetch on purpose
    ▼  15 raw hits with cosine similarities
    │  floor filter → dedupe by policy_id → stitch parts → inject guaranteed clauses
    ▼  RetrievalResult { hits[], rejected[], top_similarity }
```

Hold on to one distinction while you read: **`KBDocument` is about the document, `Chunk` is about
the index.** The loader never thinks about token budgets; the chunker never re-reads a file. Two
separate concerns, two separate modules, and that is why the chunker is testable with zero
dependencies installed.

---

## 2. `src/utils/config.py`

Three ideas in 35 lines.

```python
REPO_ROOT = Path(__file__).resolve().parents[2]
```

`__file__` is this file's path. `.resolve()` makes it absolute (and follows symlinks).
`.parents[2]` walks up three levels: `config.py` → `src/utils` → `src` → repo root. So the repo
root is derived from where the *code* lives, never from where you happened to run the command.
This is why `python scripts/build_index.py` works from any directory. Relative paths like
`data/knowledge_base` in the YAML resolve through `resolve()`, which joins them onto `REPO_ROOT`.

```python
@functools.lru_cache(maxsize=None)
def load_yaml(name: str) -> dict[str, Any]:
```

`lru_cache` memoises on the argument. The first `load_yaml("app_config.yaml")` reads and parses
the file; every later call with the same string returns the same dict object without touching
disk. `app_config()` gets called from a dozen places and this makes that free.

One trap worth knowing now: because it returns the *same* dict, mutating what you get back
mutates it for everyone. Read config, don't edit it.

---

## 3. `src/retrieval/document_loader.py`

**Takes:** the text of one markdown file. **Hands back:** a `KBDocument`.

### The regexes at the top

```python
CLAUSE_HEADING = re.compile(r"^###\s+([A-Z]{2,4}-\d{2,4})\s*[—–-]\s*(.+?)\s*$")
```

Read it left to right: start of line, `###`, whitespace, then **capture group 1** = 2–4 capital
letters, a hyphen, 2–4 digits (`FEE-001`, `CON-011`). Then optional whitespace, then a dash from
the set `[—–-]` — em dash, en dash, or ASCII hyphen — then **capture group 2** = the title,
non-greedy up to trailing whitespace and end of line.

Two deliberate choices in there. Accepting three kinds of dash means a hand-edit that loses the
em dash doesn't silently drop a clause from the index. And `(.+?)` is non-greedy so that
`\s*$` can claim the trailing spaces rather than the title swallowing them.

### The dataclasses

```python
@dataclass
class Clause:
    policy_id: str
    title: str
    body: str
    section: str
```

`@dataclass` writes `__init__`, `__repr__` and `__eq__` for you from the annotations. Compare
that to using a dict: `clause["policy_id"]` typos silently return `KeyError` at runtime and your
editor can't autocomplete. `clause.policy_id` is checked by the type checker and discoverable.
For anything with a fixed known shape, reach for a dataclass.

```python
    @property
    def family(self) -> str:
        return self.policy_id.split("-")[0]
```

A `property` is a *derived* value that looks like an attribute. `clause.family` — no parentheses.
The rule of thumb: if a value can always be computed from the fields, make it a property rather
than a field. It can never fall out of sync, and nobody can set it to something wrong.

### `parse_markdown` — a two-phase state machine

**Phase one, the header loop.** Walks lines from the top, filling `doc_title`, `front_matter`, and
`scope_lines` until it finds the first non-blockquote content line after the scope note. That
line's index becomes `body_start`.

```python
        if not doc_title and (m := DOC_TITLE.match(line)):
            doc_title = m.group(1)
```

The `:=` is the **walrus operator**: assign and test in one expression. Without it you'd write
the match to a variable on one line and test it on the next, or call `.match()` twice. `not
doc_title and ...` means only the *first* `# ` line wins — `#` also introduces sub-headings later
in the file.

Note the `for ... else` at the end of that loop. `else` on a `for` runs **only if the loop
finished without `break`** — so it's the "we never found a body" case, and it sets
`body_start = len(lines)`. This is a genuinely obscure Python feature and one of the few places
it reads better than a flag variable.

**Phase two, the body loop.** Walks from `body_start`, holding three pieces of mutable state:
the current `## ` section name, the current `Clause` being filled, and a list of lines that
belong to the section itself rather than to any clause.

The pattern to notice is the pair of closures:

```python
    def flush_clause() -> None:
        nonlocal clause, clause_lines
        if clause is not None:
            clause.body = _clean(clause_lines)
            doc.clauses.append(clause)
        clause, clause_lines = None, []
```

`nonlocal` lets an inner function rebind a variable from the enclosing function (as opposed to
`global`, which reaches module scope). Without it, `clause = None` inside `flush_clause` would
create a new local and the outer `clause` would never change.

This **accumulate-then-flush** shape is the standard way to parse line-oriented formats: every
time you hit a boundary (a new heading), finish the thing you were building and start a fresh
one. Then flush once more after the loop, for the last item — miss that final flush and you
silently lose the last clause of every file. That bug is so common it's worth remembering the
symptom: *"everything works except the last one."*

### The 60-character floor

```python
        if current_section and len(body) > 60:
            doc.sections.append(Section(title=current_section, body=body))
```

Some `## ` headings are pure containers — `## 2. Fee reversals (FEE)` has no text of its own,
only clauses beneath it. Indexing those would put near-empty chunks in the store competing for
retrieval slots. 60 characters is a crude "does this carry content" test. Crude is fine here; the
`test_parse_clauses_and_sections` test pins the behaviour so you'd notice if it started dropping
real sections.

---

## 4. `src/retrieval/chunking.py`

**Takes:** `KBDocument`s. **Hands back:** `Chunk`s ready to embed.

### The one idea that makes this file click

```python
@dataclass
class Chunk:
    chunk_id: str
    text: str        # what the LLM will read
    embed_text: str  # what we actually embed
    metadata: dict[str, Any]
```

**Two texts per chunk.** `embed_text` is prefixed with the document title and section heading,
because the embedder needs help telling five same-shaped policy files apart. `text` is just the
clause, because the doc title is noise in a prompt and costs tokens.

Almost every RAG tutorial conflates these into one string. Nothing requires that. Once you see
that the *searchable representation* and the *readable representation* are separate, a lot of
retrieval problems become easy: you can put keywords, synonyms, or a generated summary into
`embed_text` without polluting what the model reads.

### Dependency injection for the token counter

```python
def estimate_tokens(text: str) -> int:
    words = len(text.split())
    punctuation = len(re.findall(r"[|:;,.\-/()$%]", text))
    return int(words * 1.45 + punctuation * 0.25) + 2
```

```python
def chunk_document(doc, cfg=None, count_tokens: Callable[[str], int] | None = None):
    count = count_tokens or estimate_tokens
```

`count_tokens` is a **function passed as a parameter**. `Callable[[str], int]` reads as "takes one
str, returns an int". Tests and `--dry-run` pass nothing and get the dependency-free estimate;
`build_index.py` passes `embedder.count_tokens`, the real HuggingFace tokenizer.

This is dependency injection, and it buys something concrete: `tests/test_chunking.py` runs in
about a second with no torch installed. Had the tokenizer been imported at the top of this
module, every test would need a 2 GB dependency and a model download. When you're deciding where
to put an import, ask *"does this force a dependency on people who don't need it?"*

`1.45` is calibrated for BERT-family subword tokenisers on prose with tables — deliberately a
slight over-estimate, so the dry-run is conservative relative to the real count.

### `_atoms` — the smallest unit you're willing to split between

```python
    for para in (p for p in re.split(r"\n\s*\n", body) if p.strip()):
        if count(para) <= budget:
            out.append(para)
            continue
        rows, current = [], []
        for line in para.splitlines():
            ...
```

Split on blank lines first, giving paragraphs. But a markdown table is **one paragraph** — no
blank lines inside it — and the decision quick-reference tables are the longest blocks in the KB.
So any paragraph still over budget gets broken again on single newlines, i.e. table rows.

I found this the hard way: the first version only split on paragraphs, and
`troubleshooting_faq::sec-6-decision-quick-reference` came out at 489 tokens against a 480
ceiling, having been "split" into exactly one part. The split function returned without error
and the chunk was over budget anyway. Worth internalising: **a splitter that can't split must
say so, or you get silent violations of your own invariant.**

The `(p for p in ... if p.strip())` is a **generator expression** — same syntax as a list
comprehension with parentheses instead of brackets. It yields items one at a time instead of
building a list. Here it's mostly style; on large data it's a memory difference.

### `_split_on_boundaries` — the packing loop

```python
    budget = max(cfg.max_tokens - header_tokens, 64)
```

The header (`doc title / section / ### FEE-001 — title`) gets prepended to **every** part, so its
cost comes out of the budget before packing starts. This was the actual bug behind that 489-token
chunk: the body fit in 480, the body-plus-header didn't. The `max(..., 64)` is a floor so a
pathologically long header can't drive the budget to zero and loop forever.

```python
    for atom in atoms:
        if current and count("\n\n".join([*current, atom])) > budget:
            parts.append(current)
            carry = []
            for prev in reversed(current):
                if count("\n\n".join([prev, *carry])) > cfg.overlap_tokens:
                    break
                carry.insert(0, prev)
            current = [*carry, atom]
        else:
            current.append(atom)
```

Greedy packing: keep adding atoms until the next one would overflow, then close the part and
start a new one. The inner loop builds the **overlap** by walking backwards through the part just
closed, taking whole trailing atoms while they fit in the 75-token overlap budget, then prepends
them to the new part.

Overlap by whole paragraphs, not by a sliding token window. A repeated half-sentence is noise in
an embedding; a repeated numbered condition is a complete thought and keeps each part readable
alone. `[*carry, atom]` is unpacking-into-a-new-list — same as `carry + [atom]`, and it's the
idiom you'll see everywhere in modern Python.

### `chunk_document` — three loops, three chunk types

The scope chunk first (one per document — this is what makes *absence* of coverage retrievable),
then clauses, then sections. Each follows the same shape:

```python
        head = header(clause.section, clause.heading)
        body_parts = (
            [clause.body]
            if count(f"{head}\n{clause.body}") <= cfg.max_tokens
            else _split_on_boundaries(clause.body, cfg, count, count(head))
        )
```

A **conditional expression** (`X if cond else Y`). Reads as: if the whole thing fits, one part;
otherwise split it. `head` is computed once and reused, both for the fit test and as the
`header_tokens` argument — earlier I computed it twice inside the loop, which was harmless but
made the coupling between the two easy to break.

`header` itself is a closure over `doc` and `cfg`, which is why it can be called with just the
section and heading.

Then the metadata. Look at the whole dict once, because every field is there to answer a question
someone later actually asks:

* `part_index` / `part_count` — the retriever uses `part_count > 1` to know it must stitch.
* `citable` — computed here, at index time, from config. `CON-010` gets `False`. Encode the rule
  in the data rather than re-deriving it in the drafting node from a list of IDs.
* `content_hash` — the *file's* hash, copied onto every chunk from it. That's how
  `build_index.py` asks "has this file changed?" with one `collection.get()`.

One constraint you can't see in the code: **Chroma metadata values must be `str`, `int`, `float`
or `bool`.** No lists, no nested dicts. That's why `family` is a string rather than a list of
tags — and why, if you later want multi-valued metadata, you'll be encoding it as a delimited
string or filtering in Python.

### `chunk_all`'s last four lines

```python
    ids = [c.chunk_id for c in out]
    if len(ids) != len(set(ids)):
        dupes = {i for i in ids if ids.count(i) > 1}
        raise ValueError(f"duplicate chunk_ids -- indexing would silently drop one: {dupes}")
```

`len(list) != len(set(list))` is the standard duplicate check — sets discard duplicates, so a
size mismatch means there were some. This matters because Chroma's `upsert` is keyed on ID: two
chunks sharing an ID means the second overwrites the first, no error, and a clause quietly
disappears from your index. Raising here converts a silent data-loss bug into a loud crash at
build time. **Invariants you can cheaply assert, assert.**

---

## 5. `tests/test_chunking.py`

Read this next, before the harder modules — tests are the spec at its shortest.

The `SAMPLE` string at the top is a miniature KB file: front matter, scope note, a definitions
table, two clauses. Every structural feature of a real file, in 30 lines. Building a small
synthetic fixture beats loading a real file for unit tests — you can see the whole input at once,
and a KB edit can't break your tests for reasons unrelated to the code.

Two tests are worth calling out.

```python
    assert "under warranty" in doc.clauses[0].body
```

That is **design decision D1 written as an executable assertion.** The whole clause-aware
chunking argument is "conditions must stay attached to the entitlement that they qualify". This
line fails the moment someone reintroduces blind windowing.

```python
def test_no_chunk_exceeds_the_embedding_window() -> None:
    cfg = app_config()["retrieval"]["chunking"]
    ceiling = cfg["max_tokens"]
    assert ceiling <= 512, "ceiling must stay inside bge-small's 512-token window"
```

This one reads **config**, not code. If someone edits `app_config.yaml` back to 800 because the
old LLD said so, the test fails. Tests can guard configuration, and for a project where the
config *is* the tuning surface, they should.

The `if __name__ == "__main__":` block at the bottom walks `globals()` for names starting with
`test_` and calls them, so `python tests/test_chunking.py` works without pytest installed. Small
kindness to your future self on a fresh machine.

---

## 6. `src/retrieval/vector_store.py`

First file with real dependencies. Two classes: `Embedder` (text → vectors) and `KBVectorStore`
(vectors → disk and back).

### Lazy imports

```python
class Embedder:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", ...) -> None:
        from sentence_transformers import SentenceTransformer  # heavy: import lazily
```

An import inside a function runs when the function is called, not when the module loads. So
`import src.retrieval.vector_store` costs nothing, and `tests/test_chunking.py` can import the
retrieval package on a machine with no torch. Use this for genuinely heavy or optional
dependencies; normal imports still belong at the top.

### The asymmetry — the detail most people miss

```python
    def embed_documents(self, texts):
        vectors = self.model.encode(list(texts), batch_size=..., normalize_embeddings=...)

    def embed_query(self, text):
        vector = self.model.encode(f"{self.query_prefix}{text}", ...)
```

`bge-*-en-v1.5` was **trained** with an instruction prefix on the query side only:
`"Represent this sentence for searching relevant passages: "`. Documents get nothing. Embed both
sides identically and everything still "works" — you just quietly lose a few points of recall,
with no error to tell you.

This is the general shape of embedding-model bugs. They don't crash. They degrade. Which is why
the eval harness in this phase exists before any of the interesting agent work.

`normalize_embeddings=True` scales every vector to unit length. For unit vectors, cosine
similarity and dot product are the same thing, which makes the cosine distance Chroma reports
well-behaved.

### Forcing cosine, and surviving two Chroma APIs

```python
        kwargs = {"name": self.collection_name, "embedding_function": None}
        try:
            collection = self.client.get_or_create_collection(
                **kwargs, configuration={"hnsw": {"space": "cosine"}}
            )
        except TypeError:
            collection = self.client.get_or_create_collection(
                **kwargs, metadata={"hnsw:space": "cosine"}
            )
```

Chroma's default distance is **L2**, and every threshold in this project is a cosine similarity.
Get this wrong and `similarity_floor: 0.35` silently means nothing at all — the code runs, the
numbers look plausible, the floor never fires correctly.

Chroma moved this setting between major versions, so we try the newer keyword and catch
`TypeError` — the error Python raises for an unexpected keyword argument — then fall back. Catch
the *specific* exception, never bare `except:`. And `**kwargs` unpacks the dict into keyword
arguments, so the shared parts aren't written twice.

`embedding_function=None` tells Chroma "I'll supply the vectors myself". If you let Chroma own
the embedding function it would apply the same function to queries and documents, and the
asymmetric prefix above would be impossible.

Then `_collection_space` reads the setting back and `_open_collection` raises if it isn't cosine.
Asserting the thing you just configured sounds redundant right up until the day you open an index
built by an older version of the code.

### `query` — inverting the distance once

```python
        for cid, doc, meta, dist in zip(
            result["ids"][0], result["documents"][0],
            result["metadatas"][0], result["distances"][0],
            strict=True,
        ):
```

Chroma returns **lists of lists** because it supports batched queries; we send one query, so
everything is `[0]`. `zip` walks four lists in lockstep, and `strict=True` (Python 3.10+) raises
if they aren't the same length instead of silently stopping at the shortest — exactly the kind of
mismatch that would otherwise show up later as missing hits.

```python
                    "similarity": round(1.0 - float(dist), 4),
```

The inversion happens **once, here**. Distance-vs-similarity confusion (is lower better or worse?)
is a top-three source of retrieval bugs. Convert at the boundary, and every layer above works in
one direction only.

### `get_by_policy_ids`

```python
        where = {"policy_id": {"$in": ids}} if len(ids) > 1 else {"policy_id": ids[0]}
```

Chroma's `where` is a small Mongo-ish query language. `$in` matches any of a list. This is a
metadata **lookup**, not a vector search: no embedding, no similarity, just "give me the chunks
whose `policy_id` is one of these". Used for guaranteed-context injection and for stitching parts
back together — both cases where we know exactly what we want and similarity is irrelevant.

---

## 7. `src/retrieval/query_builder.py`

Shortest module in the phase and the one most likely to move your numbers.

```python
@dataclass
class QuerySignals:
    subject: str = ""
    message: str = ""
    intent: str = ""                                    # filled by triage from P2
    entities: list[str] = field(default_factory=list)
    product_area: str = ""
    category: str = ""
```

`field(default_factory=list)` instead of `= []`. This matters: a mutable default in a function or
dataclass is created **once**, at definition time, and shared by every instance — so one
instance appending to it changes the default for all future instances. `default_factory` calls
`list()` fresh per instance. This is one of Python's classic footguns and worth committing to
memory now.

Every field defaults to empty, so P1 can construct a `QuerySignals` with only the fields it has
and P2 can fill in the rest without touching a call site.

```python
def normalise(text: str, max_words: int = 90) -> str:
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6:
        text = text.lower()
```

De-shouting. `sum(c.isupper() for c in letters)` works because `True` is `1` in a numeric context
— summing booleans to count them is idiomatic. The `letters and` guard prevents division by zero
on a message with no letters. Threshold 0.6 rather than 1.0, because real shouting is rarely
perfectly uniform.

Why bother? An all-caps rant embeds differently from the same words in lower case — the tokeniser
splits unknown uppercase words into different subword pieces. You're then searching with a vector
partly shaped by the shouting rather than the content.

```python
    if signals.message and (not signals.intent or len(signals.subject.split()) < 4):
```

Only lean on the raw message when triage hasn't given us an intent (all of P1), **or** when the
subject is uselessly short. `"Fee from March"` is three words and tells you almost nothing; the
message has the $35 and the date.

The composition order — intent, entities, subject, product area, message excerpt — is the
priority order, because the message excerpt is what gets truncated when the budget runs out. Put
your most discriminating signals where they can't be cut.

---

## 8. `src/retrieval/retriever.py`

The one object the graph will call. Everything else in the phase feeds this.

### `Hit` and `RetrievalResult`

`Hit` is a flattened view of a Chroma result — metadata dict lifted into named fields, so callers
write `hit.policy_id` instead of `hit["metadata"]["policy_id"]`.

`similarity: float | None`, and the `None` is load-bearing: an **injected** clause was never
scored, and reporting `0.0` for it would be a lie that quietly corrupts every metric downstream.
`None` means "this question doesn't apply here". You'll see the distinction respected everywhere:

```python
    @property
    def below_floor(self) -> bool:
        return not any(h.similarity is not None for h in self.hits)
```

Reads as: "no hit here was actually *retrieved*" — all that survived is injected context. Guard
with `is not None`, never with truthiness, since `0.0` is falsy but is a real score.

`RetrievalResult`'s derived values are all properties or small methods — `below_floor`,
`scope_signal`, `policy_ids()`, `source_files()`, `context_block()`. Nothing is stored twice.

```python
    def policy_ids(self, *, citable_only: bool = False) -> list[str]:
        return list(dict.fromkeys(h.policy_id for h in self.hits if h.policy_id and ...))
```

`dict.fromkeys(iterable)` is the **order-preserving dedupe** idiom: dict keys are unique and,
since 3.7, keep insertion order. `set()` would dedupe but scramble the ranking, and ranking is
information we want to keep.

The `*` in the signature forces `citable_only` to be passed by keyword. `policy_ids(True)` is
unreadable at the call site; `policy_ids(citable_only=True)` isn't. Use this for boolean
parameters, always.

### `resolve_guaranteed_policy_ids` — a module-level function, not a method

It takes the rules dict and the ticket signals and returns policy IDs. It touches no `self`, so
it isn't a method — which means the tests can call it with a hand-written dict and a fake set of
known IDs, no store and no model required. **If a function doesn't need instance state, don't
make it a method.**

```python
    for entry in wanted:
        if any(ch in entry for ch in "*?["):
            matches = sorted(fnmatch.filter(known_policy_ids or set(), entry))
            if not matches:
                log.warning("guaranteed_context pattern %r matched no policy IDs", entry)
```

`fnmatch` is glob-style matching (`CON-*`) for strings — the same syntax as shell wildcards, much
easier to read in a YAML config than a regex. Patterns expand against the IDs **actually in the
index**, so adding a `CON-012` to the KB picks it up for free, and a typo expands to nothing plus
a warning rather than crashing.

Note `log.warning("... %r ...", entry)` — the value is passed as an argument, not f-string
interpolated. That's the logging convention: formatting only happens if the message is actually
emitted, and log aggregators can group by the template.

### `retrieve` — read this in five beats

**Beat 1, over-fetch.**

```python
        raw = self.store.query(query, k=max(k * 3, k + 6))
```

Ask for far more than `k`. Dedupe and the floor both *remove* candidates, so if you asked for
exactly 5 you'd end up with 3. The `max(k*3, k+6)` keeps a sane minimum when `k` is small. This
is the standard shape of any retrieve-then-filter pipeline: **fetch wide, narrow deliberately.**

**Beat 2, dedupe by policy ID.**

```python
        for item in raw:
            pid = str(item["metadata"].get("policy_id", ""))
            key = pid if (pid and self.dedupe_by_policy_id) else item["chunk_id"]
            if key not in best:
                best[key] = item
                ordered_keys.append(key)
            elif item["similarity"] > best[key]["similarity"]:
                best[key] = item
```

Two structures on purpose: `best` maps key → winning item, `ordered_keys` remembers the order
keys were **first** seen. When a better part of an already-seen clause shows up, we upgrade the
item but leave the position alone — so a clause keeps the rank of its best-matching fragment
rather than jumping around. Non-clause chunks fall back to `chunk_id`, which is unique, so they
never merge.

Without this, `TRB-002`'s two parts would occupy two of five slots and push out a different
clause. That's the difference between five clauses in context and four.

**Beat 3, the floor.** Anything under `similarity_floor` goes to `result.rejected` rather than
being dropped. Kept because `scripts/query_kb.py` prints them and because "what *nearly* matched"
is diagnostic gold when you're tuning the floor.

**Beat 4, stitching.**

```python
            if self.stitch_clause_parts and hit.policy_id and int(item["metadata"].get("part_count", 1)) > 1:
                hit = self._stitch(hit, self.store.get_by_policy_ids([hit.policy_id]))
```

Only when `part_count > 1`, so the extra lookup costs nothing for the 58 clauses that never split.
`_stitch` sorts the parts by `part_index`, then walks paragraphs keeping a `seen` set to drop the
overlap that was deliberately duplicated at index time.

The idea to keep: **the index is chunked, the prompt is not.** Retrieval matched a fragment; the
model gets the whole clause, because the conditions it must check may live in the other fragment.

**Beat 5, injection.** Resolve the guaranteed IDs, subtract the ones already retrieved, fetch the
rest by metadata, mark them `injected=True`, and **append after** the `k` dense hits. Injected
clauses don't compete for slots — they're additional. `if len(kept) >= k: break` earlier caps only
the dense side.

### `context_block`

```python
            tag = f"[{h.label}]"
            if not h.citable:
                tag += " (INTERNAL GUIDANCE - do not quote or cite to the customer)"
```

Prompt-ready context where each block is labelled with what the model may do with it. "Never cite
CON-010" is only enforceable if the prompt says *which block is CON-010*. Instructions about
context have to live next to the context, not in a system prompt three thousand tokens away.

### `build_default_retriever`

A **factory function**: reads config, constructs `Embedder`, `KBVectorStore` and `Retriever`,
wires them together. Note this is the only place in the module that imports config. `Retriever`
itself takes plain arguments and knows nothing about YAML, so a test can build one with fake
values in two lines. Keep your classes ignorant of where their configuration came from and put
the wiring in one factory.

```python
    if store.count() == 0:
        raise RuntimeError("the vector index is empty -- run `python scripts/build_index.py` first")
```

Fail with the command the reader should run next. An error message is a user interface.

---

## 9. `src/evaluation/retrieval_eval.py`

### `CaseResult` — one record per ticket, metrics as properties

```python
    @property
    def doc_recall(self) -> float | None:
        if not self.expected_sources:
            return None
        hit = len(set(self.expected_sources) & set(self.retrieved_sources))
        return hit / len(set(self.expected_sources))
```

`&` is set intersection. So: *of the documents that should have been found, what fraction were?*
That's recall. Note it's **per ticket** — a ticket expecting three documents and finding two
scores `0.67`, and the report averages those per-ticket fractions. That's "micro-averaged", and
it's the honest choice here because a partial hit is genuinely partial credit: two of the three
policies the answer depends on is better than none and worse than all.

`None` for "not applicable" again, filtered out before averaging with
`[r.doc_recall for r in with_policy if r.doc_recall is not None]`.

Three related properties — `doc_recall`, `doc_recall_system`, `clause_recall` — differ only in
which sets they compare. Writing them as separate small properties instead of one function with a
mode flag keeps each name meaningful at the call site.

### The metric that keeps us honest

`doc_recall` counts **dense hits only**. `doc_recall_system` counts injection too. Both are
reported. Why the split: injection puts `abusive_content_policy.md` into context on *every*
ticket via CON-010/CON-011, so `doc_recall_system` collects a free point on every ticket whose
expected sources include the conduct policy. That's a true statement about the system and a
useless statement about the embedder.

The gate is set on the dense number. **When a metric can be inflated by something other than the
thing you're trying to measure, report both and gate on the strict one.**

### The mirror-image error

```python
        absence_detected=_mean([1.0 if (r.below_floor or r.scope_signal) else 0.0 for r in no_policy]),
        false_absence_rate=_mean([1.0 if r.below_floor else 0.0 for r in with_policy]),
```

`absence_detected` over the 8 no-policy tickets: did the floor fire when it should?
`false_absence_rate` over the other 99: did it fire when it shouldn't?

Lowering the floor improves the second and wrecks the first. They're printed adjacent
deliberately, because optimising one in isolation is how you end up escalating easy tickets and
never notice. **Every threshold has a metric it improves and a metric it damages. Find the second
one and report it next to the first.**

### The sweep

```python
        for k in ks:
            for floor in floors:
                rep = evaluate(retriever, k=k, similarity_floor=floor, limit=args.limit)
                print("  " + rep.summary())
```

`evaluate` takes `k` and `similarity_floor` as parameters that **override** the retriever's
configured values, so one loaded model and one open index serve the whole grid. Had those been
baked in at construction time, each cell would mean re-instantiating everything.

Exit code is `0 if report.passed else 1` — so the gate can eventually be a CI check rather than
something you remember to eyeball.

---

## 10. `scripts/build_index.py`

Read the **order of the checks**, because the order is the point:

1. Parse and chunk (cheap, no model).
2. `max_tokens > embedder.max_seq_length` → `return 2`. Refuse before embedding anything.
3. Distinct policy IDs `!= 59` → `return 2`. A KB that parses to the wrong number of clauses does
   not get indexed at all — better an empty-handed failure than a plausible-looking partial index.
4. Any chunk over the ceiling → `return 2`.
5. Only now: embed and write.
6. After writing, verify every parsed policy ID is retrievable from the store.

**Validate before you mutate.** Once a bad index is on disk, everything downstream lies to you,
and the failure surfaces three phases later as "the model keeps hallucinating fee limits".

The incremental skip:

```python
        if indexed.get(doc.source_file) == doc.content_hash:
            log.info("  %-32s unchanged (%s) - skipped", doc.source_file, doc.content_hash)
            continue
        store.delete_source(doc.source_file)
        written += store.upsert(doc_chunks)
```

Delete-then-upsert rather than upsert alone. Upsert only overwrites IDs it sees; if you *renamed*
a clause, the old `chunk_id` would still be sitting in the index, matching queries, citing a
policy ID that no longer exists. Deleting the file's chunks first makes the index a true
reflection of the source.

Exit codes: `0` success, `1` reserved for a failed gate in the eval script, `2` for "refused to
build". `raise SystemExit(main())` at the bottom is the conventional way to turn a return value
into a process exit status.

---

## 11. Where each design decision lives in code

| Decision | Code |
| --- | --- |
| D1 clause-aware chunking | `chunking.chunk_document`, asserted by `test_parse_clauses_and_sections` |
| Absence must be retrievable | the `scope` chunk in `chunk_document`; `RetrievalResult.scope_signal` |
| Never cite CON-010 | `citable` metadata (index time) → `context_block` label (prompt time) |
| Guaranteed context | `config/routing_rules.yaml` → `resolve_guaranteed_policy_ids` → injection in `retrieve` |
| Don't embed the raw rant | `query_builder.build_query` |
| Cosine thresholds | `KBVectorStore._open_collection` + the inversion in `query` |
| The P1 gate | `retrieval_eval.DOC_RECALL_GATE`, exit code |

---

## 12. Five experiments, with predictions

Each is one edit, one command, and a specific thing to look at. Predictions given so you can
check yourself — and if a prediction is wrong, that's the interesting outcome, not a failure.

**1. Watch the query builder earn its place.**

```
python scripts/query_kb.py --ticket TCK-1084 --raw
```
Prediction: the built query surfaces app/troubleshooting clauses; the raw message surfaces
conduct clauses and buries the actual fault. This is the single most convincing five minutes in
the phase.

**2. Break the token ceiling on purpose.** Set `max_tokens: 800` in `app_config.yaml`, then:

```
python tests/test_chunking.py
python scripts/build_index.py
```
Prediction: the test fails on the `<= 512` assertion, and the build refuses with exit code 2
before embedding anything. You've just watched two independent guards catch the same mistake —
that redundancy is intentional.

**3. Turn off dedupe.** `dedupe_by_policy_id: false`, rebuild nothing, just re-run the eval.
Prediction: a small drop in clause recall, because `TRB-002`'s two parts now occupy two slots on
mobile-deposit tickets. Small effect, exactly one clause affected — worth seeing how a structural
choice shows up as a number.

**4. Sweep the floor and find the crossover.**

```
python -m src.evaluation.retrieval_eval --sweep-floor 0.15,0.25,0.35,0.45,0.55
```
Prediction: `absence_detected` climbs monotonically with the floor, `false_absence_rate` climbs
with it too, and doc recall falls off at the top end. The floor you want is the highest one that
keeps `false_absence_rate` at `0.000`.

**5. Test the LLD's original guess.** `embed_scope_note: true`, rebuild the index (the embedded
text changed, so you *must* rebuild), re-run the eval.
Prediction: doc recall flat or slightly up, clause recall slightly down — the scope note makes all
seven FEE clauses look more alike to the embedder. If that's what you see, the default stays off
and you now have a number to cite for it rather than an argument.

Whatever you find on 4 and 5, write the numbers into
`docs/lld_p1_retrieval.md` §10 as answers. That's what the open-questions section is for.
