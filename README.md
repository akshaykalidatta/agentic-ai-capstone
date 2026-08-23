# Support Ticket Triage & Resolution Agent

An agentic pipeline that reads a bank support ticket, finds the policy that governs it, decides
what to do, drafts a reply, and hands the whole thing to a human. Nothing reaches a customer.

Fictional US retail bank (Northgate), 150 synthetic tickets, a 59-clause knowledge base, and a
golden set that was built around specific failure modes rather than around easy wins.

---

## Run it in two minutes, with nothing installed

```bash
pip install pydantic PyYAML pytest

python -m src.main --gate                                    # every offline gate
python -m src.main --ticket TCK-1143 --engine bm25 --no-model --walk -v
python -m pytest tests/ -v                                   # 109 tests
```

`--no-model` runs the deterministic layers only; `--engine bm25` uses the lexical retriever,
which needs no index and no torch; `--walk` executes the graph in plain Python. Between them,
the whole pipeline runs on a bare checkout.

## Run it for real

```bash
pip install -r requirements.txt
cp .env.example .env                     # then set GROQ_API_KEY=gsk_... (free tier is enough)

python scripts/build_index.py            # ~84 chunks, a minute on CPU
python -m src.main --sample              # the 13-ticket dev batch
python -m src.main --all                 # the full queue, arrival order

python -m src.evaluation.retrieval_eval --compare    # bm25 vs dense vs hybrid
python -m src.evaluation.route_eval                  # route accuracy + critical errors
python -m src.evaluation.report --latest --markdown  # everything, scored
python -m src.logging.replay --latest --ticket TCK-1125
```

## Review it as a human

Set `graph.checkpointer: sqlite` in `config/app_config.yaml` first — interactive review
suspends the graph mid-run and refuses to start on a checkpointer that dies with the process.

```bash
python -m src.main --sample --hitl interactive   # each ticket stops at the review gate
streamlit run app/streamlit_app.py               # the queue, the review screen, the metrics
```

`docs/human_review.md` explains the mechanic; `docs/demo_script.md` is a five-minute
walkthrough. **P7's gate has not been run yet** — see `docs/pipeline.md` §8.

---

## What it does, in one picture

```
triage ──safety──────────────────────────► safety_escalate ─┐
   │                                                         │
   └─normal─► preconditions ─► retrieve ─► analyse_policy ─► route_decision
                                  ▲            │                   │
                                  └─refine─────┘                   ▼
                                                            score_confidence
                                                                   │
                              hitl_gate ◄── validate_draft ◄── draft_reply
                                  │              └──repair───────┘
                                  └─► audit_log
```

Three bounded loops (retrieval refinement, confidence recheck, draft repair), each capped and
each ending in escalation, because a human is the only safe fallback. One branch: a
safety-critical flag skips retrieval entirely, so a crisis reply can never be drafted with fee
clauses sitting in the context window.

Full detail: **[`docs/pipeline.md`](docs/pipeline.md)**.

---

## Design decisions worth knowing before you read the code

| | |
| --- | --- |
| **Clause-aware chunking** | One chunk per policy clause, not blind token windows. A window splits a clause from its own conditions, and groundedness becomes unmeasurable — the citation is right and the content is invented. |
| **Preconditions computed in Python** | *"I don't think I've ever asked before"* reads identically whether the record says 0 prior reversals or 1, and those need opposite routes. Eligibility is arithmetic over fields, handed to the model as fact. |
| **Composed confidence** | Five measurable signals, with the model's own opinion capped at 10%. A self-reported number never dips, and a number that never dips cannot drive a loop. |
| **Two route proposals** | The rule engine and the model each propose one, independently. Their *disagreement* is the hard-case detector, and it costs nothing to label. |
| **Route before draft** | Drafting first makes the draft the evidence for the route. On the 45 hard tickets that failure is near-total. |

---

## Where things live

```
config/           app_config · model_config · routing_rules   — every threshold is data
data/             tickets · knowledge_base · evaluation       — hand-authored, validated
app/
  streamlit_app.py  the review surface                        — rendering only
src/
  main.py         CLI: run a batch, print the report, run the gates
  graph/          graph_state · nodes · edges · support_graph
  hitl/           reviewer_actions · approval_queue · review_service
  agents/         base · triage · policy · response           — every model call
  routing/        rules_engine · target_map · confidence · thread_pressure
  safety/         policy_checker                              — deterministic patterns
  retrieval/      loader · chunking · vector_store · bm25 · hybrid · retriever
  memory/         customer_thread_store                       — case history across tickets
  evaluation/     retrieval_eval · route_eval · evaluators · report
  logging/        trace_logger · audit_logger · replay
tests/            none needing an API key or an index
docs/             architecture (HLD) · pipeline (how) · human_review (P7) · demo_script
```

---

## Measured status

Everything here was run in this repo. Nothing is projected.

| Gate | Result |
| --- | --- |
| P0 topology | **green** — 10 structural checks |
| P1 doc recall@5, BM25 alone | **0.921** (gate 0.90), hard 0.937, false-absence 0.000 |
| P1 dense / hybrid | **not measured** — needs `scripts/build_index.py` |
| P2 safety-critical flagged | **2/2**, zero false positives across all 150 |
| P2 tone traps not flagged | **6/6** |
| P3 rule engine | fires on 20/150, **100% correct where it fires** |
| P3 route accuracy, deterministic only | 0.447 overall, **0 critical errors** |
| P4 citation integrity | **1.000** |
| P5 confidence in-band | **0.851** (gate 0.70) |
| P6 audit replayability | **150/150** |
| P6 thread pressure | TCK-1125 lifts to Executive Complaints; TCK-1109 stays REFUSE |
| P8 groundedness | 0.761 (gate 0.85) — retrieval-bound |
| P8 no-policy handling | 0.625 — the 5 of 8 the scope signal reaches without a model |
| P7 six reviewer actions | **6/6** over the real nodes and routers, each with its distinct effect |
| **P7 restart durability** | **not yet run** — needs a real `langgraph-checkpoint-sqlite` |
| Tests | **109 passing**, plus 22 cases in `tests/test_hitl.py` that have not been run |

The deterministic 0.447 is a floor, not a disappointment: with no model there is no second
route proposal, so every non-REFUSE ticket escalates. Safe, unhelpful, zero critical errors.

## What is built but unverified

P7 (the Streamlit review app) and Phoenix tracing are written, and everything reachable without
the LangGraph runtime has been exercised — the six actions and the regeneration loop over the
real nodes and routers, every review screen, the queue fold, the metrics. What is **not** proven
is the part that needs a real install: `interrupt()` suspending inside LangGraph, `Command`
resuming it, and a suspended review surviving a process restart on the sqlite checkpointer.
Phoenix has never been run with `observability.enabled: true`.

`docs/pipeline.md` §8 lists exactly what was checked and the three commands that close the gap.

Also open: run the dense and hybrid retrieval gates, run `route_eval` with a key, and fit the
confidence weights against the 107 golden bands.
