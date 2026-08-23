# `notebooks/` — scratch space, not deliverables

Three notebooks are planned. Nothing in `src/` may import from here, and no number reported
anywhere should come from here — a notebook result cannot be re-run by a stranger from the
README, which is P9's gate.

- `rag_experimentation.ipynb` — poking at retrieval by hand. The scriptable version already
  exists as `scripts/query_kb.py`; use the notebook for the questions that need a plot.
- `langgraph_flow_demo.ipynb` — walk one ticket node by node with the state visible between
  steps. The clearest way to *see* what `docs/p0_code_walkthrough.md` describes.
- `evaluation_analysis.ipynb` — confusion matrices and confidence calibration plots over the
  JSON reports in `outputs/evaluation_reports/`. Reads reports; never computes metrics.

That last rule is the one worth holding: evaluators live in `src/evaluation/` and write JSON.
Notebooks read that JSON. A metric computed in a notebook exists only on your machine.
