# `app/` — the human review surface (P7)

`streamlit_app.py` is the only place in the project that renders anything, and it is the only
place that does not decide anything. Every decision lives in `src/hitl/review_service.py`.

```bash
streamlit run app/streamlit_app.py     # needs graph.checkpointer: sqlite
```

Two things about it are architectural rather than cosmetic:

- **The screen shows the retrieved clauses *beside* the draft.** A reviewer shown only the
  draft is judging fluency; a reviewer who can see what the agent read is judging
  groundedness — which is the thing that actually matters, and it turns the reviewer into the
  groundedness metric's ground truth (HLD §7).
- **The app talks to `src/hitl/`, never to `src/graph/` directly.** Interactive review works by
  the `hitl_gate` node calling `interrupt()`, which suspends the graph and returns control
  here; the app resumes it with the reviewer's decision. The UI needs no knowledge of the graph
  beyond "resume this thread_id", and the checkpointer must be `sqlite` (see
  `config/app_config.yaml → graph.checkpointer`) or a restart loses every suspended review.

The full account — suspend/resume and why the node runs twice, the queue/checkpointer
relationship, the six actions, what is measured, and how to reproduce restart durability by
hand — is `docs/human_review.md`.
