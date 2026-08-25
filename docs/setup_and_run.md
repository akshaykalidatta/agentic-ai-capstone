# Setup and run

You need Python 3.11+ and a free [Groq API key](https://console.groq.com/keys). About 15 minutes,
most of it waiting for `pip`.

## 1. Clone and install

```powershell
git clone https://github.com/akshaykalidatta/agentic-ai-capstone.git
cd agentic-ai-capstone

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS and Linux: `python3 -m venv .venv` then `source .venv/bin/activate`.

Every command below runs from the repo root, with the venv active.

This pulls in `torch` for local embeddings, roughly 2 GB. If PowerShell blocks the activate
script, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first.

## 2. Add your API key

Copy `.env.example` to `.env` at the repo root, and set one line:

```
GROQ_API_KEY=gsk_...
```

`src/utils/config.py` loads it on import, so every entry point picks it up. The free tier is
enough; responses are cached under `.cache/llm/`.

## 3. Enable durable review

In `config/app_config.yaml`:

```yaml
graph:
  checkpointer: sqlite      # default is: memory
```

The review app suspends the graph mid-run and resumes it after a person decides. On `memory` that
state dies with the process, so the app refuses to start.

## 4. Build the index

```powershell
python scripts/build_index.py
```

About 84 clause-level chunks. The first run downloads the embedding model (~130 MB) and takes a
minute on CPU.

## 5. Run the agent

```powershell
python -m src.main --sample
```

13 tickets. One line each: route, confidence, escalation target, node count. Audit records land
in `outputs/audit_logs/`.

Use `--all` for the full 150-ticket queue (~750 model calls), or `--limit 25` for a shorter pass.

## 6. Open the review app

```powershell
python -m streamlit run app/streamlit_app.py
```

Opens `http://localhost:8501`. `Ctrl+C` to stop.

To fill the queue, use the sidebar expander **Queue tickets for review**: set *How many*, press
**Run them**.

Three screens, chosen from the sidebar:

- **Queue** — awaiting review, least confident first. Filter by route, or to only the tickets
  where the rules and the model disagreed. Pick one and press **Review this ticket**.
- **Review** — the retrieved policy clauses on the left, the agent's decision and draft on the
  right, so you can see what the reply was built from. Below them: an editable draft, the action,
  a comment box, and **Submit decision**. Six actions are available: `APPROVE`,
  `APPROVE_AND_ROUTE`, `EDIT`, `REQUEST_REGENERATION`, `REJECT`, `ESCALATE_OVERRIDE`.
- **Metrics** — what review measured, split by mode.

Decisions are appended to `outputs/reviews.jsonl`.

## 7. Evaluation report

```powershell
python -m src.evaluation.report --latest --markdown
```

Scores the latest run and writes JSON and Markdown to `outputs/evaluation_reports/`. It reads
audit records, so it needs no model calls.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `No module named src` | `cd` to the repo root |
| `No module named streamlit` | Activate the venv, re-run step 1 |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| `GROQ_API_KEY is not set` | Step 2. A shell variable of the same name overrides `.env` |
| Empty queue with a banner in Streamlit | `graph.checkpointer` is still `memory` — step 3 |
| Queue entry shows checkpoint `missing` | Queued while on `memory`. Fix step 3, queue again |
| Port 8501 in use | Add `--server.port 8502` |
| Repeated 429s | Groq free-tier rate limit. Retried automatically; re-run to hit the cache |

## Everything, in order

```powershell
git clone https://github.com/akshaykalidatta/agentic-ai-capstone.git
cd agentic-ai-capstone

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# copy .env.example to .env, set GROQ_API_KEY
# set graph.checkpointer: sqlite in config\app_config.yaml

python scripts/build_index.py
python -m src.main --sample
python -m streamlit run app/streamlit_app.py
python -m src.evaluation.report --latest --markdown
```
