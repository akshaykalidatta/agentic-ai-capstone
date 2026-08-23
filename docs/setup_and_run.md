# Setup and run, end to end

Steps only. Every command is copy-pasteable **PowerShell**, run from the repo root
(`C:\Users\Srinivas\Desktop\Akshay\GitHub\agentic-ai-capstone`). Config and data paths are
anchored to the repo root by `src/utils/config.py`, but `python -m src.*` needs the root as the
working directory.

Steps marked **[UNRUN]** have never been executed in this repo. They are the open gates.

---

## Part A — Setup (once)

### 1. Open a shell at the repo root

```powershell
cd C:\Users\Srinivas\Desktop\Akshay\GitHub\agentic-ai-capstone
```

### 2. Activate the virtual environment

```powershell
.\.venv\Scripts\Activate.ps1
python --version        # expect 3.13.15
```

If PowerShell blocks the script, allow it for this shell only, then re-run the activate line:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

The prompt should now be prefixed `(.venv)`. **Every command below assumes it is.**

### 3. Install the remaining dependencies

`torch`, `chromadb`, `sentence-transformers`, `langgraph`, `groq` and `pytest` are already in the
venv. `streamlit`, `langgraph-checkpoint-sqlite` and `arize-phoenix` are **not** — they are what
Parts F and G need.

```powershell
pip install -r requirements.txt
```

Confirm the three that were missing:

```powershell
python -c "import streamlit, langgraph.checkpoint.sqlite, phoenix; print('P7 + P8 deps ok')"
```

---

## Part B — Prove it offline (no API key, no index)

### 4. Run the gate

```powershell
python -m src.main --gate
```

Expect `GATE GREEN` and 13 `[PASS]` lines: 150 tickets parse, 107 golden records, topology,
BM25 doc recall@5 ≈ 0.92, safety 2/2, tone traps 6/6. Exit code 0. **If this is red, stop here** —
nothing downstream is trustworthy.

### 5. Run the test suite

```powershell
python -m pytest tests/ -v
```

Expect 109 passing, plus 22 cases from `tests/test_hitl.py`.

**[UNRUN]** `tests/test_hitl.py` has never executed — it needs the packages from step 3. Run it on
its own first so a failure is unambiguous:

```powershell
python -m pytest tests/test_hitl.py -v
```

If the whole file reports **skipped**, `langgraph-checkpoint-sqlite` is not installed — the module
calls `pytest.importorskip` at the top, so a missing package looks like a clean run. Go back to
step 3.

The one that closes P7's gate:

```powershell
python -m pytest tests/test_hitl.py::test_a_suspended_review_survives_a_process_restart -v
```

### 6. Run one ticket, deterministic

```powershell
python -m src.main --ticket TCK-1143 --engine bm25 --no-model --walk -v
```

`--no-model` = deterministic layers only (patterns, rule engine, retrieval, confidence).
`--engine bm25` = lexical retrieval, no index and no torch. `--walk` = plain-Python graph walker,
no LangGraph. Expect a 12-node trace, no loops fired.

---

## Part C — Build the vector index

### 7. Build it

```powershell
python scripts/build_index.py
```

Incremental — it skips unchanged files, so an already-built `.chroma\` prints skips and exits fast.
Expect ~84 chunks over 59 clauses. First run downloads `BAAI/bge-small-en-v1.5` (~130 MB) and takes
about a minute on CPU. Force a rebuild with `--force`; inspect without embedding with `--dry-run`.

Sanity-check retrieval by hand:

```powershell
python scripts/query_kb.py "my overdraft fee from last week, can I get it back"
```

### 8. **[UNRUN]** Close the P1 retrieval gate

```powershell
python -m src.evaluation.retrieval_eval --compare
```

Runs bm25, dense and hybrid side by side. BM25 alone is the recorded baseline at **0.921**
(gate 0.90). If hybrid does not beat it, `retrieval.bm25.enabled: false` in
`config\app_config.yaml` is a legitimate answer — record the number either way.

---

## Part D — Run with a model

### 9. Put the Groq key in `.env`

Once, at the repo root — not in `config\`, which is committed:

```powershell
Copy-Item .env.example .env
notepad .env
```

Set the one line and save:

```
GROQ_API_KEY=gsk_...
```

`src/utils/config.py` loads `.env` into the environment on import, so every entry point picks it
up — `python -m src.main`, `streamlit run`, `pytest`, `scripts/build_index.py`. No shell command,
and nothing to re-set when you open a new terminal.

Verify:

```powershell
python -c "import src.utils.config, os; print('key set' if os.environ.get('GROQ_API_KEY') else 'MISSING')"
```

A shell variable still overrides the file, for trying a second key without editing it:

```powershell
$env:GROQ_API_KEY = "gsk_other"        # this shell only; .env is ignored while it is set
```

`.env` is gitignored and `tests/test_config.py` asserts both that and that `.env.example` never
carries a value — the key cannot reach a commit by accident.

Responses are cached on disk at `.cache\llm\` keyed by model + prompt + temperature, so re-runs
are nearly free and free-tier 429s are retried with backoff.

### 10. Run the dev batch

```powershell
python -m src.main --sample
```

13 tickets, hybrid retrieval, both route proposals live. One line per ticket: route, confidence,
escalation target, node count.

### 11. Run all 150

```powershell
python -m src.main --all
```

Arrival order, single-threaded — the 4 escalating customer threads break silently otherwise.
~750 model calls on a cold cache; expect several minutes. Add `-v` for per-node traces, or
`--limit 25` for a shorter pass. Audit records land in `outputs\audit_logs\`.

---

## Part E — Score the run

### 12. Route accuracy and critical errors

```powershell
python -m src.evaluation.route_eval
```

Targets: ≥70% overall, ≥55% hard, **zero critical errors**. The recorded 0.447 is the
deterministic floor (`--no-model`), not a result — with no model there is no second proposal, so
everything escalates.

### 13. Full report and replay

```powershell
python -m src.evaluation.report --latest --markdown
python -m src.logging.replay --latest --ticket TCK-1125
python -m src.logging.replay --latest --check
```

`report` prints critical errors first, aggregate last, and writes to
`outputs\evaluation_reports\`. `replay --check` turns "could you defend this decision six months
from now" into an exit code; the recorded result is 150/150 replayable.

---

## Part F — Human review (P7)

### 14. Switch to a durable checkpointer

Edit `config\app_config.yaml`:

```yaml
graph:
  checkpointer: sqlite      # was: memory
```

Interactive review calls `interrupt()` to suspend the graph mid-run and **refuses to start** on
`memory`, on purpose — a paused review would vanish the moment the process exits. If the app shows
an empty queue with a banner, this is the setting it is complaining about.

### 15. Queue tickets for review

```powershell
python -m src.main --ticket TCK-1078 --hitl interactive --no-model
```

Expect `TCK-1078 ... AWAITING REVIEW` — suspended, not finished. Confirm it is on disk:

```powershell
Get-Content outputs\approval_queue.jsonl
Get-Item outputs\checkpoints.sqlite
```

For a fuller queue: `python -m src.main --sample --hitl interactive`.

### 16. **[UNRUN]** Open the review app

```powershell
python -m streamlit run app/streamlit_app.py
```

Opens on `http://localhost:8501`. Three screens: **Queue** (least-confident first, filterable to
rule/model disagreements), **Review** (draft beside the clauses it was built from, plus case
history), **Metrics** (split by HITL mode, never pooled).

This step **is** the restart-durability test: the process from step 15 is gone, so a queue entry
listed as checkpoint `suspended` proves sqlite survived it. `missing` means step 15 ran on
`memory`. Open the ticket, confirm the draft and confidence match step 15, approve it, then:

```powershell
Get-Content outputs\reviews.jsonl -Tail 1
python -m src.logging.replay --latest --ticket TCK-1078
```

Six reviewer actions are available: `APPROVE`, `APPROVE_AND_ROUTE`, `EDIT`,
`REQUEST_REGENERATION`, `REJECT`, `ESCALATE_OVERRIDE`. `EDIT` never overwrites the original draft
and `ESCALATE_OVERRIDE` never rewrites the agent's route — both keep the denominator of the metric
they feed. `REQUEST_REGENERATION` is capped at 3 passes (`graph.loop_caps.review_regeneration`).

The sidebar can also queue tickets itself ("Queue tickets for review"), which is the shorter path
for a demo — but then step 15 and step 16 share one process, and the restart is no longer tested.

---

## Part G — Tracing (P8)

### 17. **[UNRUN]** Turn Phoenix on

Terminal 1:

```powershell
phoenix serve
```

UI on `http://localhost:6006`, OTLP on the same port. Then edit `config\app_config.yaml`:

```yaml
observability:
  enabled: true             # was: false
```

Terminal 2 (activate the venv again there):

```powershell
python -m src.main --sample
```

The run banner should end `| tracing=phoenix`. Spans appear under project
`support-ticket-agent`, tagged with the run id, one trace per ticket. Tracing can never fail a
run: a missing or unreachable Phoenix downgrades to a log line and the batch continues — so check
the banner, not your assumption. Set `enabled: false` when done.

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `No module named src` | Wrong working directory | `cd` to the repo root |
| `Activate.ps1 cannot be loaded` | Execution policy | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| `GROQ_API_KEY is not set` | No `.env` at the repo root, or the line is blank | Step 9 |
| `.env` there but ignored | A shell variable is set and wins | `Remove-Item Env:\GROQ_API_KEY` |
| `[SKIP] P1 retrieval (hybrid)` in the gate | No vector index | Step 7 |
| Empty queue + banner in Streamlit | `graph.checkpointer: memory` | Step 14 |
| Queue entry shows checkpoint `missing` | Ticket was queued while on `memory` | Step 14, then re-queue |
| `--hitl interactive needs the real graph` | `--walk` passed too | Drop `--walk` |
| `tests/test_hitl.py` all skipped | `langgraph-checkpoint-sqlite` missing | Step 3 |
| `'JsonPlusSerializer' object has no attribute 'dumps'` | `langgraph-checkpoint-sqlite` 2.x against `langgraph-checkpoint` 4.x | Fixed in `src/graph/checkpointing.py`; make sure you are on that commit |
| Repeated 429s | Free-tier rate limit | Expected; retried with backoff. Re-run to hit the cache |
| Run dies on one ticket | `run.stop_on_error: true` | Leave it `false` to continue past failures |

---

## The whole thing, in order

```powershell
cd C:\Users\Srinivas\Desktop\Akshay\GitHub\agentic-ai-capstone
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python -m src.main --gate                                # offline gate
python -m pytest tests/ -v                               # 109 + 22 tests
python scripts/build_index.py                            # ~84 chunks
python -m src.evaluation.retrieval_eval --compare        # P1 gate

Copy-Item .env.example .env ; notepad .env               # GROQ_API_KEY=gsk_...
python -m src.main --sample                              # 13 tickets
python -m src.main --all                                 # 150 tickets

python -m src.evaluation.route_eval                      # accuracy + critical errors
python -m src.evaluation.report --latest --markdown       # everything, scored
python -m src.logging.replay --latest --check            # auditability

# set graph.checkpointer: sqlite in config\app_config.yaml
python -m src.main --sample --hitl interactive
python -m streamlit run app/streamlit_app.py
```

Deeper reading: `docs\pipeline.md` (how it works), `docs\architecture.md` (why),
`docs\human_review.md` (the review mechanic), `docs\demo_script.md` (a five-minute walkthrough).
