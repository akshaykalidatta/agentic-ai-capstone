# Build prompt — the frontend and integration work that remains

Hand this to a fresh agent session working in `agentic-ai-capstone`. It is a specification, not
a tutorial: it says what must be true when you are done, names the traps, and leaves the design
inside those constraints to you.

Everything in the repo that runs headlessly is already built and measured. What is left is
**P7 (the Streamlit review app)**, **P8's tracing half (Phoenix)**, and **P9's demo**. Those
three share one property: none of them can be verified without a browser, an external service
or a person, which is why they are specified here rather than already written.

---

## 0. What already exists — do not rebuild it

Read `README.md` and `docs/pipeline.md` first. The short version:

| Layer | State |
| --- | --- |
| Graph: 12 nodes, 3 bounded loops, safety bypass | built, 23 topology tests |
| Retrieval: dense + BM25 + RRF fusion | built, BM25 alone scores doc recall@5 **0.921** |
| Triage + deterministic safety patterns | built, 2/2 critical flagged, 0 false positives |
| Rule engine, route reconciliation, confidence | built, rules 100% correct where they fire |
| Drafting, citation and content validation | built, citation integrity **1.000** |
| Case history and thread pressure | built, TCK-1125 lifts to Executive Complaints |
| Audit log and replay (`src/logging/replay.py`) | built, **150/150** records replayable |
| Evaluators and report (`src/evaluation/`) | built, runnable offline against any past run |
| **109 tests**, none needing an API key or an index | passing |

Interfaces you will use, already in place:

- `src/hitl/reviewer_actions.py` — the six actions as data. **Do not redefine them.**
- `src/graph/nodes.py::hitl_gate` — works for `auto` and `simulate`; raises for `interactive`.
- `src/graph/edges.py::after_review` — `REQUEST_REGENERATION` is the only re-entry, already
  capped by `graph.loop_caps.review_regeneration`.
- `src/graph/support_graph.py::build_graph(checkpointer=...)` — sqlite path already fixed to
  own its connection with `check_same_thread=False`.
- `src/logging/replay.py::render` / `missing_evidence` — the decision chain, already formatted.
- `src/evaluation/report.py::build` — the scored report as a dict.
- `config/app_config.yaml` — `hitl.mode`, `graph.checkpointer`, `graph.sqlite_path`,
  `outputs.approval_queue`, `outputs.reviews`.

Repo conventions you must follow:

- **Comments are short.** Module docstring 3–8 lines; function docstring one line by default.
  Expand only where a choice looks arbitrary or a line prevents a specific failure — then name
  the failure. Explain *why*, never *what*.
- **Long descriptive names** beat short ones plus a comment.
- **One document per phase.** You will write `docs/human_review.md` and update
  `docs/pipeline.md` §8. Nothing else.
- **Delete unused code.** No speculative helpers.
- Thresholds and labels live in `config/*.yaml`, never inlined.
- **Report what you measured, not what you expect.** A half-working P7 is more useful known
  than assumed.

---

# Part A — P7: human review

## A1. The contract

From HLD §7, non-negotiable:

1. **Review is a gate, not a notification.** Nothing reaches a customer under any
   configuration. Every path — including the safety bypass — passes through `hitl_gate`.
2. **The reviewer sees the retrieved clauses beside the draft.** This is the load-bearing UX
   decision, not a layout preference. A reviewer shown only the draft is judging fluency; one
   who can see what the agent read is judging groundedness, which is the thing that matters,
   and it makes them the ground truth for that metric.
3. **Six actions, each with a distinct consequence.**
4. **Three modes are architectural.** `interactive` (this phase), `simulate`, `auto`. Every
   reported metric must state which mode produced it. `interactive` must never silently fall
   back to `auto` — that would let someone publish an "interactive" number no human ever saw.
5. **Edit rate and override rate** are the two production quality signals. Capture both.

**The gate:** all six actions work end to end, and interactive mode survives an app restart
mid-review.

## A2. Architecture

**`app/streamlit_app.py` is a view. It contains no decisions.**

Every piece of logic — loading the queue, resuming a thread, recording a decision, computing
edit distance — lives in `src/hitl/`. Two reasons, and the second is the one that bites:
Streamlit re-executes the whole script on every widget interaction, so logic in the app file
runs an unpredictable number of times; and Streamlit code is awkward to test, while a service
module is not.

```
app/streamlit_app.py            rendering only
src/hitl/review_service.py      the adapter: queue, resume, record. All logic.
src/hitl/approval_queue.py      append-only JSONL index of pending reviews
```

`review_service.py` replaces the `approval_ui_stub.py` named in `lld_notes.md` §10. Note the
deviation in your doc: it is the real adapter, not a stub, and calling it one would mislead the
next reader.

Dependency direction, unchanged: `app/` → `src/hitl/` → `src/graph/`. Nothing in `src/graph/`
imports from `src/hitl/` beyond `reviewer_actions`, and nothing imports from `app/`.

## A3. Suspend and resume — the hard part

Rewrite `hitl_gate` so `interactive` mode calls LangGraph's `interrupt()`:

```python
from langgraph.types import interrupt

decision_payload = interrupt({...what the reviewer needs to see...})
```

`interrupt()` raises on the first pass, suspending the graph. Resume with
`Command(resume=<decision>)`, and **the node re-executes from the top** — `interrupt()` then
returns the injected value instead of raising.

**That re-execution is the trap.** Anything above that line happens twice. Keep it pure: no
writes, no counter increments, no logging that implies a single occurrence. Side effects go
after the interrupt returns.

`auto` and `simulate` must keep working exactly as they do now. They are ordinary nodes and
must not call `interrupt()`; if they did, every eval run would hang.

## A4. Checkpointing and thread identity

Durability across a restart is entirely the checkpointer's job. `memory` dies with the process,
so P7 requires `sqlite`. `_default_checkpointer` already owns its connection correctly — read
the comment there before changing it; `SqliteSaver.from_conn_string` is a `@contextmanager` in
recent versions and returning it directly hands back the wrong object.

Add `langgraph-checkpoint-sqlite` to `requirements.txt` with a comment saying P7 needs it.

`thread_id = f"{run_id}:{ticket_id}"` — already the format `main.py` uses. Keep it exactly.
It is what lets the app resume the right ticket, and what makes a restart recoverable, since
the thread id reconstructs from a queue entry alone. Do not invent a second scheme.

## A5. Finding what is pending

Two sources, and you need both:

- **The checkpointer** is the truth about whether a thread is suspended. `graph.get_state(config)`
  returns a snapshot whose `.next` and `.tasks` show a node waiting.
- **The queue file** (`outputs/approval_queue.jsonl`) makes the pending set *enumerable*
  without scanning every thread id ever created.

Append-only. Never rewrite it to mark something done — append a completion record and derive
the pending set by folding. An index you can rewrite is an index that can disagree with the
checkpointer, and the checkpointer is the one that is right. When they disagree, say so
visibly rather than guessing.

## A6. Recording decisions

Append to `outputs/reviews.jsonl`, one line per decision: `run_id`, `ticket_id`, `action`,
`comments`, `reviewed_at`, `reviewer`, the original draft, the edited draft when there is one,
and the agent's route alongside any route the reviewer overrode.

Separate from the audit log because the audit log is per run and this is per decision — a
ticket reviewed twice after a regeneration has one audit record and two review records.

## A7. Streamlit's execution model

Non-negotiable, given the whole script reruns on every interaction:

- `@st.cache_resource` for the compiled graph and the checkpointer connection. Never
  `@st.cache_data`, which tries to hash and copy the value.
- `st.session_state` for the current ticket and any in-progress edit, keyed so moving to the
  next ticket cannot inherit the previous one's text box.
- Explicit, stable `key` on every widget. Auto-generated keys collide across reruns and you
  get a text area that refuses to clear.
- `st.rerun()` after an action, rather than mutating the rendered page.
- A batch run blocks the UI. Show progress; do not freeze silently for two minutes.

## A8. Screens

### Review screen — the one that matters

Two columns, side by side, because that adjacency is requirement 2.

**Left — what the agent read.** Every chunk with policy ID, source file, similarity (and BM25
score when hybrid produced one), and whether it was retrieved or injected as guaranteed
context. Chunks with `citable=False` must be visually distinct and labelled internal — CON-010
is a drafting standard for staff, and quoting it at a customer is both a citation error and a
strange reply.

**Right — what the agent decided and wrote.** The draft in an editable text area, plus:

- Route, escalation target, confidence with its five components broken out.
- **Both proposals side by side** (`rule_route`, `llm_route`). When they disagree, say so
  loudly — that disagreement is the hard-case detector and the most useful thing a reviewer
  can be told.
- Preconditions **with their inputs**. "Eligible" is an assertion; "eligible — no prior
  reversal in 12 months, fee 7 days old" is evidence, and the reviewer is checking evidence.
- Safety flags with evidence spans and which detector fired.
- Loop counters, and which loops capped.
- Thread pressure and prior tickets when `customer_history` is non-empty. TCK-1125 is the
  fourth contact in an escalating story and reads completely differently with that context.
- The customer's message and earlier turns. **Mark `system` turns clearly** — they are internal
  events, not customer speech, and a reviewer skimming will otherwise read "Source IP
  geolocation: inconsistent" as something the customer wrote.

`src/logging/replay.py::render` already assembles most of this as text. Reuse its ordering.

**One thing the screen must get right or the ticket is wrong:** when
`escalation_visible_to_customer` is `False`, the reviewer must see the referral *and*
understand the draft must not mention it. Render it as an unmissable banner, not a field among
fields. This is TCK-1078 — a third-party access request refused while the account is quietly
referred for abuse review, where naming the referral warns exactly the person the account
holder may need protecting from.

**Empty evidence is correct on the bypass.** A safety-critical ticket arrives with
`retrieved == []` by design. Say so on screen rather than rendering a blank panel that looks
broken.

### Queue screen

Ticket id, subject, route, confidence, escalation target, whether a loop capped, whether the
proposals disagreed. Filter by route and by "disagreed", sort by confidence ascending — the
least confident decisions are the ones most worth a human's time.

### Metrics screen

Read `outputs/reviews.jsonl` and call `src.evaluation.report.build` for the rest. Show, labelled
with the mode that produced them: **edit rate**, **override rate**, median edit size as a
proportion of the original, route distribution, disagreement rate, and the confidence
calibration table `confidence_eval` already returns.

Do not compute metrics in the app file, and do not recompute anything `src/evaluation/` owns.
This screen reads and renders.

## A9. The six actions

Take them from `src/hitl/reviewer_actions.py`.

| Action | Effect |
| --- | --- |
| `APPROVE` | Resume; terminate into audit. |
| `APPROVE_AND_ROUTE` | Same, target confirmed. Default when a target exists. |
| `EDIT` | Store `edited_draft` **alongside** the original. Edit size is a quality signal you cannot compute if you overwrote what you would measure against. |
| `REQUEST_REGENERATION` | The only re-entry. The comment feeds `draft_reply`, which already accepts `reviewer_comment`. Capped by `review_regeneration`; disable the button at the cap rather than letting a click fail. |
| `REJECT` | Nothing out, nothing regenerated. Record and terminate. |
| `ESCALATE_OVERRIDE` | Record the agent's route and the reviewer's, marked a route disagreement. |

## A10. Testing

`tests/test_hitl.py`, following the existing suite's conventions: short docstrings saying what
failure the test prevents, no API key, no built index. Use the BM25 retriever and
`tests/fake_llm.py`, which exist for exactly this.

Cover:

- All six actions, each asserting its distinct downstream effect.
- **Restart durability.** Interrupt a graph, discard the in-memory objects, rebuild from the
  sqlite file, resume, assert the run completes with pre-interrupt state intact. **This is the
  gate — write it first.**
- Regeneration re-enters drafting, changes the prompt, terminates at `audit_log`, and stops at
  the cap.
- An edited draft leaves the original recoverable.
- The queue folds correctly when a ticket is reviewed twice.
- `auto` and `simulate` never call `interrupt()`.
- A silent escalation is flagged to the reviewer and absent from the draft.

`streamlit.testing.v1.AppTest` can drive the app headlessly — use it for a smoke test and put
the real assertions in the service tests. If a behaviour is hard to test through `AppTest`,
that is a sign it belongs in `review_service.py`.

**One trap the existing suite has hit twice:** a test that passes on an empty set. Assert the
denominator, not just the score. `test_evaluation.py` has three tests that passed for that
reason before it was caught.

---

# Part B — P8's tracing half: Phoenix

The evaluators are built and passing. What is missing is tracing, and the boundary matters:
**traces answer "what did it do and how long did it take"; metrics answer "was it right".**
Only the second needs the dataset's labels, and the observability tool must never become the
reason the evaluation does not exist.

Keep it minimal. This was decided explicitly and should not be expanded without asking:

```bash
pip install arize-phoenix openinference-instrumentation-langchain
phoenix serve                                    # UI on localhost:6006
```

```python
from phoenix.otel import register
register(project_name="support-ticket-agent", auto_instrument=True)
```

LangGraph runs on LangChain callbacks, so the LangChain instrumentor captures every node, model
call and retrieval span with no further work.

Requirements:

- Behind a config flag (`observability.enabled`, default **false**) and a lazy import. A
  missing Phoenix must never break a run — the 109 tests pass today without it and must
  continue to.
- Register once per process, not per ticket.
- The `run_id` must appear on the trace so a Phoenix span can be matched to an audit record.
- Do **not** move any metric computation into Phoenix. Custom evaluators stay as our own
  Python. Phoenix experiments over the golden set are a stretch goal, after everything else.
- Add the two packages to `requirements.txt` marked P8.

Verify by running `--sample` with tracing on and confirming spans appear for every node. Report
whether you actually saw them; do not assume.

---

# Part C — P9's demo

`docs/demo_script.md`: a five-minute walkthrough a stranger can follow. The P9 gate is that
they can run the project from the README alone, and the README is already written — your job is
the narrative that shows the design decisions doing something visible.

Suggested spine, one ticket each, but choose your own if you find better ones:

1. **TCK-1143** — the happy path. FEE-001 courtesy reversal, rules and model agree, high
   confidence, clean citation.
2. **TCK-1019** — the safety bypass. Show `retrieved == []` on screen. This is the one that
   makes the architecture legible.
3. **TCK-1077** — the tone trap. Threatens to post on Twitter, still routes on the request.
   Show it next to TCK-1019 and the discrimination becomes obvious.
4. **TCK-1078** — the silent referral. Refused, referred, and the draft says nothing.
5. **TCK-1125** — the escalating thread. Show the three prior tickets and the target lifting
   to Executive Complaints.
6. A disagreement ticket — rules and model differ, the confidence loop fires.
7. `python -m src.logging.replay --latest --ticket TCK-1125` — the whole decision chain,
   reconstructed without re-running the agent.

Include the exact commands, and say which HITL mode each number came from.

---

# Traps, named

1. **The node re-runs on resume.** Everything before `interrupt()` executes twice.
2. **`check_same_thread=False`**, or sqlite refuses the Streamlit worker thread.
3. **`@st.cache_data` on a compiled graph** fails confusingly. Use `@st.cache_resource`.
4. **Widget state leaking between tickets.** Stable, ticket-scoped keys.
5. **Rewriting the queue file** to mark items done, letting it drift from the checkpointer.
6. **Letting `interactive` fall back to `auto`** when nothing is connected. Fail loudly.
7. **Reducer keys.** Writing `trace`, `notes`, `loops_capped` or `retrieval_log` means
   returning only the delta, never the concatenated whole, and a node re-entered by a loop
   needs a `not in` guard. This has already caused one bug here.
8. **The safety bypass reaches review too**, with empty evidence. Handle it as correct.
9. **Tests that pass on an empty set.** Assert the denominator.
10. **Phoenix breaking a run.** Lazy import, config flag, default off.

---

# Deliverables

```
app/streamlit_app.py            rendering only
src/hitl/review_service.py      queue, resume, record — all logic
src/hitl/approval_queue.py      append-only pending index
src/graph/nodes.py              hitl_gate rewritten for interrupt/resume
src/utils/tracing.py            Phoenix registration, lazy, flagged off
config/app_config.yaml          observability section
requirements.txt                streamlit, langgraph-checkpoint-sqlite, arize-phoenix
tests/test_hitl.py
docs/human_review.md            one doc, ~250 lines
docs/demo_script.md
docs/pipeline.md                §8 updated with the P7 gate result
```

`docs/human_review.md` covers: how to run it, the suspend/resume mechanic and why the node
re-runs, the queue/checkpointer relationship and which wins, the six actions, what the review
screen shows and why the columns sit side by side, what is measured, and the
restart-durability procedure as something the reader can reproduce. Link to `pipeline.md`
rather than duplicating it.

---

# Out of scope

Named because HLD §11 settled them and re-opening one by accident is the risk:

- **No sending, ever.** No email, no CRM write-back, no webhook.
- **No authentication.** A local surface, not a deployment.
- **No multi-user concurrency.** One reviewer. Two processes resuming one thread is undefined.
- **No metric computation in the UI.** `src/evaluation/` owns scoring.
- **No expansion of the Phoenix surface** beyond `register(auto_instrument=True)`.

---

# Definition of done

- [ ] Six actions work, each with its distinct effect, each tested.
- [ ] A ticket paused mid-review survives a full process restart and completes.
- [ ] `auto` and `simulate` unchanged; the existing **109 tests still pass**.
- [ ] `python -m src.main --gate` still green.
- [ ] Silent escalations unmissable to the reviewer and absent from the draft.
- [ ] Edit rate and override rate computed from `reviews.jsonl` and displayed.
- [ ] No logic in `app/streamlit_app.py`.
- [ ] Phoenix off by default; a run with it off is byte-identical to today's.
- [ ] `docs/human_review.md` and `docs/demo_script.md` written; `pipeline.md` §8 updated.
- [ ] Every number quoted anywhere states the HITL mode that produced it.
