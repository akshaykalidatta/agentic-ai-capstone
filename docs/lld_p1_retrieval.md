# LLD — P1 Retrieval (knowledge base ingestion + index)

Companion to `docs/architecture.md` (HLD) and `docs/lld_notes.md` (parking lot).
Scope: everything that turns five markdown policy files into something the agent can search.
Written at the start of P1, as agreed.

**Gate for this phase:** `doc recall@5 ≥ 0.90` on the 99 golden tickets that have a policy.
Nothing in `src/graph/` gets written until that number is green.

---

## 1. Why this is not part of LangGraph

This is worth being explicit about, because it is the most common structural mistake in RAG
projects.

There are two different jobs, and they run at different times:

| | Ingestion (this phase) | Retrieval (used by the graph) |
| --- | --- | --- |
| Runs | Once, offline, when the KB markdown changes | Once per ticket, inside a node |
| Entry point | `scripts/build_index.py` | `Retriever.retrieve(...)` |
| Cost | ~84 embeddings, a few seconds | one query embedding, ~10 ms |
| Owns | parse → chunk → embed → write `.chroma/` | query → search → filter → inject |
| Knows about LangGraph | nothing | nothing (the *node* knows about it) |

Ingestion is a build step, like compiling. If it ran inside the graph, every one of the 150
tickets in an eval run would re-embed the whole knowledge base — and we will re-run that eval
dozens of times while tuning. The index is a **build artefact**: derived from
`data/knowledge_base/`, gitignored, and reproducible with one command.

Retrieval is a function call. `src/graph/nodes.py` will eventually hold something close to:

```python
def rag_node(state: GraphState) -> dict:
    result = RETRIEVER.retrieve(
        build_query(state.query_signals),
        sentiment=state.sentiment,
        category=state.category,
        product_area=state.product_area,
    )
    return {"context": result.context_block(), "retrieved_policy_ids": result.policy_ids()}
```

That is the entire LangGraph coupling: a node reads state, calls a plain Python object,
writes state. Which is why P1 is testable and sweepable without a graph existing at all.

---

## 2. Module map

```
config/app_config.yaml          retrieval params: chunk ceiling, k, similarity floor
config/routing_rules.yaml       guaranteed-context sets, non-citable clause list
src/utils/config.py             config loading, repo-root path resolution
src/retrieval/
    document_loader.py          markdown -> KBDocument (clauses, sections, scope note, hash)
    chunking.py                 KBDocument -> Chunk[]  (D1: clause-aware)
    vector_store.py             Embedder + Chroma persistence (cosine, bge prefixes)
    query_builder.py            ticket -> search string
    retriever.py                search + floor + dedupe + stitch + guaranteed injection
src/evaluation/retrieval_eval.py   the P1 gate and the parameter sweeps
scripts/build_index.py          the offline build
scripts/query_kb.py             look at what retrieval returns, by hand
tests/test_chunking.py          runs with zero dependencies installed
```

Data flow, once:

```
data/knowledge_base/*.md
   -> load_kb()          5 KBDocument (59 clauses, 19 sections, 5 scope notes)
   -> chunk_all()        84 Chunk     (60 clause chunks, 19 section, 5 scope)
   -> Embedder           84 x 384-dim vectors
   -> .chroma/           persistent, cosine space, collection "northgate_kb"
```

Then, per ticket:

```
ticket -> build_query() -> embed_query() -> chroma.query(n=k*3)
       -> floor filter -> dedupe by policy_id -> stitch parts -> inject guaranteed
       -> RetrievalResult
```

---

## 3. Chunk schema

84 chunks, three types. Every chunk carries this metadata:

| Field | Example | Why it exists |
| --- | --- | --- |
| `chunk_id` | `refund_policy::FEE-001` | stable ID → upsert is idempotent, re-indexing never duplicates |
| `chunk_type` | `clause` / `section` / `scope` | only `clause` is citable |
| `policy_id` | `FEE-001` | the citation P4 is allowed to print; `""` for non-clauses |
| `family` | `FEE` | lets `CON-*` guaranteed-context patterns expand |
| `source_file` | `refund_policy.md` | matches the golden set's `expected_kb_sources` |
| `doc_id` | `KB-REF-2026-03` | audit trail: which version of which document |
| `section` | `2. Fee reversals (FEE)` | prepended to the embedded text |
| `title` | `One-time courtesy reversal` | human-readable label in traces |
| `citable` | `true` / `false` | `CON-010` is internal drafting standard — retrievable, never quoted |
| `content_hash` | `e0443739db29b569` | incremental re-index: skip files that have not changed |
| `part_index` / `part_count` | `0` / `1` | overflow bookkeeping; `>1` triggers stitching |
| `token_estimate` | `193` | guards the embedding window |

**Counts to watch.** 59 distinct policy IDs — the build fails hard if the parser produces any
other number, because a clause heading that loses its em dash would otherwise vanish from the
index with no error. 5 scope chunks, one per document. 19 section chunks (definitions tables,
published limits, decision quick-references).

**Two texts per chunk, on purpose.** `embed_text` is what gets embedded:
`{doc_title}\n{section}\n### {policy_id} — {title}\n{body}`. `text` is what the LLM reads:
`### {policy_id} — {title}\n{body}`. The doc title helps the embedder discriminate between
five same-shaped policy files; it is noise in a prompt. There is no rule that says the string
you embed and the string you show the model have to be the same one.

---

## 4. Correction to `lld_notes.md` §3: the ceiling is 480, not 800

`bge-small-en-v1.5` has `max_seq_length = 512`, and sentence-transformers **truncates silently**
past it — no warning, no error, no log line. An 800-token chunk would be indexed on its first
~512 tokens and the remainder would be unreachable by any query. Given that clause bodies are
where the *conditions* live, and conditions tend to come last, the failure would be
precisely: retrievable entitlement, unretrievable precondition. Exactly what D1 exists to
prevent, reintroduced through the back door.

So: `max_tokens: 480` (512 minus header room), and `scripts/build_index.py` refuses to run if
the configured ceiling exceeds the model's real window.

Only one of the 59 clauses (`TRB-002`, mobile deposit) actually overflows, plus two long
reference tables. For those, `_split_on_boundaries` splits at paragraph boundaries — and at
single-newline row boundaries inside markdown tables, since a table is one paragraph — with
75 tokens of whole-paragraph overlap. All parts keep the same `policy_id`, and the retriever
then:

1. **dedupes by `policy_id`**, keeping the best-scoring part, so a long clause cannot eat two
   of the five slots; and
2. **stitches the parts back together** before handing the clause to the model.

Net effect: the index is chunked, the prompt is not.

---

## 5. Query construction

`store.query(ticket["message"])` is the default instinct and it is wrong here. Take TCK-1084:
a paragraph of insults with a genuine app-crash complaint inside it. Embed the raw message and
the nearest neighbours are conduct clauses, because that is what the text is mostly about. The
app fault never gets retrieved, the draft answers the tone, and the ticket fails.

`build_query` composes, in order: triage intent → extracted entities → subject → product
area → a normalised excerpt of the message. Normalisation lower-cases all-caps text, strips
greeting/urgency boilerplate, and truncates.

In P1 there is no triage node, so the intent and entity slots are empty and the fallback
(subject + product area + message excerpt) is what runs. That is intentional: it measures what
retrieval can do unaided. When P2 lands and passes a real intent, these numbers should
**improve** — if they don't, triage is extracting the wrong fields, and that is worth knowing.

Compare the two side by side with `python scripts/query_kb.py --ticket TCK-1084 --raw`.

---

## 6. Similarity floor and absence detection

Chroma's default distance is L2. Every threshold here is a **cosine similarity**, so the
collection is created with `space=cosine` and `vector_store` asserts it on every open —
otherwise `1 - distance` is not a similarity and `similarity_floor: 0.35` silently means
nothing.

8 of the 107 golden tickets have `no_policy_in_kb: true`. Getting those right needs two of
three signals (per `lld_notes.md` §3):

1. top-1 below the floor after both attempts — `RetrievalResult.below_floor`
2. a scope-note chunk out-ranks every clause — `RetrievalResult.scope_signal`
3. analysis finds no deciding clause — P2/P3, not here

Signal 2 is why every document contributes a `scope` chunk. A mortgage-escrow question matches
no clause, but it does match *"does not cover mortgage or home equity escrow adjustments"*.
Absence of coverage is only detectable if the absence is written down somewhere and indexed.

The eval reports `absence_detected` (of the 8) next to `false_absence_rate` (of the 99),
because those move in opposite directions and tuning one without watching the other is how
you end up escalating easy tickets. Sweep with:

```
python -m src.evaluation.retrieval_eval --sweep-floor 0.20,0.25,0.30,0.35,0.40,0.45
```

---

## 7. Guaranteed context

Some clauses are too important to leave to a similarity score. `config/routing_rules.yaml`
declares them as data:

* every ticket → `CON-010`, `CON-011`
* `sentiment ∈ {angry, distressed}` → `CON-001`, `CON-002`
* `category == conduct_and_prohibited` → all `CON-*` (pattern-expanded against the index)
* `category == disputes_and_fees` → `DSP-006`
* `product_area == digital_access` → `ACC-007`, `ACC-010`

Injected clauses are added **on top of** k, not in competition with it, and are marked
`injected=True` so traces stay honest. `CON-010` is injected with `citable=False`, and
`context_block()` labels it *"INTERNAL GUIDANCE — do not quote or cite to the customer"*,
because "don't cite CON-010" is only enforceable if the prompt says which block is CON-010.

This is also why the eval reports doc recall twice. Injection puts
`abusive_content_policy.md` in context on *every* ticket, so the "system view" gets a free
point on every ticket whose expected sources include it. Honest measurement of the retriever
is the dense-only number, and that is what the gate is set against.

---

## 8. Metrics

| Metric | Over | Reads as |
| --- | --- | --- |
| `doc_recall` | 99 with-policy tickets, dense hits only | **the gate: ≥ 0.90** |
| `doc_recall_system` | same, incl. injection | what the model actually sees |
| `doc_recall_hard` | hard subset | where the real difficulty is |
| `full_doc_hit_rate` | 99 | fraction where *every* expected doc was found |
| `clause_recall_dense` | 99 | predicts P4 groundedness; strictly harder |
| `clause_recall_injected` | 99 | same, counting injection |
| `absence_detected` | the 8 no-policy tickets | did the floor fire when it should |
| `false_absence_rate` | 99 | did it fire when it shouldn't — want 0.000 |

Recall is micro-averaged per ticket: a ticket expecting three documents and finding two
scores 0.67, not 0. Roughly a third of the golden tickets expect 2–3 source documents, which
is why `k=5` with dedupe is tight — expect the `--sweep-k 3,5,8` run to show k=8 buying real
recall at the cost of prompt tokens. That trade-off is a P1 decision to make with numbers in
front of you, not a guess.

Every run writes a JSON report to `outputs/evaluation_reports/retrieval_eval_<ts>.json`, so
sweeps are comparable after the fact.

---

## 9. Deliberately not in this phase

* **Hybrid / BM25.** Dense-only first, because we need to know what dense costs us before
  paying for a second index. Policy IDs (`FEE-001`) are exact-match tokens that BM25 handles
  and embeddings blur, so this is the obvious first upgrade **if** the gate misses.
* **Cross-encoder reranker.** Would help clause recall; adds a second model and latency.
  Revisit only if clause recall blocks P4.
* **LLM query rewrite / the "second attempt".** Needs a model call, so it belongs with P2.
  `retrieve()` is already safe to call twice with different queries.
* **Per-family metadata filtering.** Tempting (`where={"family": "FEE"}`) and dangerous:
  filtering by predicted category means a mis-categorised ticket can never retrieve its way
  out. Keep the search unfiltered; let scores decide.

## 10. Open questions for the sweep

1. `k = 5` or `k = 8`? A third of tickets need 2–3 documents.
2. Floor at 0.35, or lower with a stricter second signal for absence?
3. Does `embed_scope_note: true` (LLD §3's original guess) help doc recall enough to justify
   spending ~120 of 480 tokens and making sibling clauses look alike?
4. Are the 19 section chunks earning their place, or do quick-reference tables crowd out the
   clause that actually decides the ticket?
