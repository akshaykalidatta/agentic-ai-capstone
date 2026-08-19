# agentic-ai-capstone

Agentic AI Bootcamp Capstone Project — Support Ticket Triage & Resolution Agent.

Design: [`docs/architecture.md`](docs/architecture.md) (HLD) ·
[`docs/lld_notes.md`](docs/lld_notes.md) (parking lot) ·
[`docs/lld_p1_retrieval.md`](docs/lld_p1_retrieval.md) (current phase)

Code: [`docs/p1_code_walkthrough.md`](docs/p1_code_walkthrough.md) — a reading guide to the
retrieval slice, in dependency order, with experiments at the end.

## Status

| Phase | | Gate |
| --- | --- | --- |
| P0 skeleton | in progress | — |
| **P1 retrieval** | **code complete, gate not yet run** | doc recall@5 ≥ 0.90 |
| P2 triage + safety | not started | 7/7 safety flagged, 6/6 tone traps survive |
| P3 routing | not started | ≥70% overall / ≥55% hard |
| P4 drafting | not started | zero hallucinated citations |

## Running P1

```bash
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt                     # pulls torch: ~2 GB, one time

python tests/test_chunking.py                       # no deps needed, runs in ~1 s
python scripts/build_index.py --dry-run             # parse + chunk, no model, no writes
python scripts/build_index.py                       # build .chroma/ (~84 chunks)

python scripts/query_kb.py --ticket TCK-1084 --raw  # see retrieval by hand
python -m src.evaluation.retrieval_eval             # the P1 gate
python -m src.evaluation.retrieval_eval --sweep-k 3,5,8 --sweep-floor 0.25,0.35,0.45
```

`.chroma/` is a build artefact — gitignored, rebuilt from `data/knowledge_base/` in seconds.
Re-run `build_index.py` after editing any KB markdown; unchanged files are skipped by content
hash.
