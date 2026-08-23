# Build prompt — P7: Human review (Streamlit) and its integration

Hand this to a fresh agent session working in `agentic-ai-capstone`. It is a specification, not
a tutorial: it says what must be true when you are done, names the traps, and leaves the design
inside those constraints to you.

---

## 0. Your task in one paragraph

Build the human review layer for the Support Ticket Triage & Resolution Agent. A reviewer must
be able to open a Streamlit app, work through tickets the pipeline has paused on, see the
evidence the agent used *beside* the reply it wrote, and take one of six actions — one of which
sends the ticket back into the graph. The pipeline must genuinely suspend and resume, not
re-run from scratch, and a browser refresh or an app restart mid-review must lose nothing.

---

## 1. Read these first

| File | Why |
| --- | --- |
| `docs/architecture.md` §7 | The review model. Non-negotiable requirements live here. |
| `docs/pipeline.md` §2, §3 | The graph, and what `hitl_gate` currently does. |
| `src/hitl/reviewer_actions.py` | The six actions, already defined as data. Do not redefine them. |
| `src/graph/nodes.py` → `hitl_gate` | The node you are replacing. Note it raises for `interactive` today. |
| `src/graph/edges.py` → `after_review` | The router. `REQUEST_REGENERATION` is the only action that re-enters. |
| `src/graph/support_graph.py` → `_default_checkpointer` | Contains a latent bug (§4.2). |
| `src/logging/audit_logger.py` | The record shape you will render. |
| `app/README.md` | Notes already written for this phase. |

Repo conventions, which this work must follow:

- **Comments are short.** Module docstring 3–8 lines; function docstring one line by default.
  Expand only where a choice looks arbitrary or a line prevents a specific failure — then name
  the failure. Explain *why*, never *what*.
- **Long descriptive names** beat short ones plus a comment.
- **One document per phase.** You will write `docs/human_review.md` and nothing else. Do not
  write a second walkthrough doc.
- **Delete unused code.** No speculative helpers for P8.
- Thresholds and labels live in `config/*.yaml`, never inlined.

---

## 2. The contract

### 2.1 What must be true (from HLD §7)

1. **Review is a gate, not a notification.** Nothing reaches a customer under any
   configuration. Every path through the graph — including the safety bypass — passes through
   `hitl_gate`.
2. **The reviewer sees the retrieved clauses beside the draft.** This is the load-bearing UX
   decision, not a layout preference. A reviewer shown only the draft is judging fluency; one
   who can see what the agent read is judging groundedness, which is the thing that matters,
   and it makes them the ground truth for that metric.
3. **Six actions, each with a distinct consequence.** Approve; approve and route; edit (both
   versions retained); request regeneration (returns to drafting with the comment as input);
   reject; escalate as an override (records a route disagreement).
4. **Three operating modes are architectural.** `interactive` (this phase), `simulate` (replay
   the golden set's expected action), `auto` (approve, for full-queue eval runs). Every
   reported metric must state which mode produced it. Do not let `interactive` silently fall
   back to `auto` — that would let someone publish an "interactive" number no human ever saw.
5. **Edit rate and override rate are the two production quality signals.** Capture both from
   the first session.

### 2.2 The gate you must pass

> All six actions work end to end, and interactive mode survives an app restart mid-review.

Concretely, demonstrable in a test:

- Each of the six actions produces the correct downstream effect (§6).
- A ticket paused at `hitl_gate`, with the Python process killed and restarted, resumes at the
  same point with the same state and completes normally.
- `REQUEST_REGENERATION` re-enters `draft_reply`, produces a *different* draft, and returns to
  review — without creating a fourth, undeclared loop.
- An edited draft is stored alongside the original, not instead of it.

---

## 3. Architecture you must follow

**`app/streamlit_app.py` is a view. It contains no decisions.**

Every piece of logic — loading the queue, resuming a thread, recording a decision, computing
edit distance — lives in `src/hitl/`. The app file reads state, calls a service, renders.

Two reasons, and the second is the one that bites: Streamlit re-executes the entire script top
to bottom on every widget interaction, so any logic in the app file runs an unpredictable
number of times; and Streamlit code is awkward to test, while a service module is not.

Modules to create:

```
app/streamlit_app.py            rendering only
src/hitl/review_service.py      the adapter: queue, resume, record. All logic.
src/hitl/approval_queue.py      append-only JSONL queue of pending reviews
```

`src/hitl/review_service.py` replaces the `approval_ui_stub.py` named in `lld_notes.md` §10.
Note the deviation in your doc: it is the real adapter, not a stub, and calling it one would
mislead the next reader.

Dependency direction, unchanged: `app/` → `src/hitl/` → `src/graph/`. Nothing in `src/graph/`
may import from `src/hitl/` beyond the existing `reviewer_actions`, and nothing anywhere may
import from `app/`.

---

## 4. Integration — the hard part

### 4.1 Suspend and resume

Rewrite `hitl_gate` so that in `interactive` mode it calls LangGraph's `interrupt()`:

```python
from langgraph.types import interrupt

decision_payload = interrupt({...what the reviewer needs to see...})
```

`interrupt()` raises on the first pass, suspending the graph. The run is resumed with
`Command(resume=<the reviewer's decision>)`, and on resume **the node re-executes from the
top** — `interrupt()` then returns the injected value instead of raising.

**That re-execution is the trap.** Anything the node does before `interrupt()` happens twice.
Keep everything above that line pure: no writes, no logging that implies a single occurrence,
no counter increments. If you need a side effect, put it after the interrupt returns.

`auto` and `simulate` must keep working exactly as they do now. They are ordinary nodes and
must not call `interrupt()`; if they did, every eval run would hang.

### 4.2 The checkpointer, and a bug to fix

Durability across a restart is entirely the checkpointer's job. `memory` (the current default)
dies with the process, so P7 requires `sqlite`.

`src/graph/support_graph.py::_default_checkpointer` currently does:

```python
return SqliteSaver.from_conn_string(str(path))
```

**Verify this against the installed version before trusting it.** In recent
`langgraph-checkpoint-sqlite` releases `from_conn_string` is a `@contextmanager` that *yields*
a saver, so this returns a context-manager object rather than a checkpointer, and the graph
fails at compile or on first write. The Streamlit-safe form is to own the connection:

```python
connection = sqlite3.connect(path, check_same_thread=False)
saver = SqliteSaver(connection)
```

`check_same_thread=False` is required because Streamlit serves requests from a worker thread
that is not the one that opened the connection. Fix this properly, and add
`langgraph-checkpoint-sqlite` to `requirements.txt` with a comment saying P7 is what needs it.

### 4.3 Thread identity

`main.py` already namespaces runs as `thread_id = f"{run_id}:{ticket_id}"`. Keep that exact
format — it is what lets the app resume the right ticket, and it is what makes a restart
recoverable, since the thread id can be reconstructed from the queue entry alone.

Do not invent a second identifier scheme for the UI.

### 4.4 Finding what is pending

Two sources, and you need both:

- **The checkpointer** is the truth about whether a thread is suspended. `graph.get_state(config)`
  returns a snapshot whose `.next` and `.tasks` tell you a node is waiting.
- **The queue file** (`outputs/approval_queue.jsonl`, path already in `config/app_config.yaml`
  under `outputs.approval_queue`) is what makes the pending set *enumerable* without scanning
  every thread id you have ever created.

The queue is a durable index, append-only. Never rewrite it to mark something done; append a
completion record instead, and derive the pending set by folding the file. An index you can
rewrite is an index that can disagree with the checkpointer, and the checkpointer is the one
that is right.

If the two ever disagree, the checkpointer wins and the app should say so visibly rather than
guessing.

### 4.5 Recording decisions

Append every reviewer decision to `outputs/reviews.jsonl` (config key `outputs.reviews`).
One line per decision, append-only, containing at minimum: `run_id`, `ticket_id`, `action`,
`comments`, `reviewed_at`, `reviewer`, the original draft, the edited draft when there is one,
and the agent's route alongside any route the reviewer overrode it with.

This file is the source for edit rate and override rate. It is separate from the audit log
because the audit log is per run and this is per decision — a ticket reviewed twice after a
regeneration has one audit record and two review records.

### 4.6 Streamlit's execution model

Non-negotiable given the whole script reruns on every interaction:

- Cache the compiled graph and the checkpointer connection with `@st.cache_resource`, never
  `@st.cache_data` — the latter tries to hash and copy the value.
- Hold the current ticket, the draft being edited, and any in-progress form state in
  `st.session_state`, keyed so that moving to the next ticket cannot inherit the previous
  ticket's text box.
- Give every widget an explicit, stable `key`. Auto-generated keys collide across reruns and
  you get a text area that refuses to clear.
- Call `st.rerun()` after an action so the queue advances, rather than trying to mutate the
  rendered page.
- Running a batch blocks the UI. Show progress (`st.status` or `st.progress`) and make it
  obvious the app is working; do not silently freeze for two minutes.

---

## 5. Screens

Three, in priority order. The first is the phase; the other two are what make it usable.

### 5.1 Review screen — the one that matters

Two columns, side by side, because that adjacency is requirement 2 from §2.1.

**Left — what the agent read.** Every retrieved chunk with its policy ID, source file,
similarity (and BM25 score when hybrid produced one), and whether it was retrieved or injected
as guaranteed context. Chunks marked `citable=False` must be visually distinct and labelled
internal — CON-010 is a drafting standard for staff and quoting it at a customer is both a
citation error and a strange reply.

**Right — what the agent decided and wrote.** The draft in an editable text area, plus:

- Route, escalation target, and confidence with its five components broken out.
- **Both proposals side by side** (`rule_route` and `llm_route`). When they disagree, say so
  loudly — that disagreement is the hard-case detector, and it is the single most useful thing
  a reviewer can be told.
- Preconditions **with their inputs**, not just their verdicts. "Eligible" is an assertion;
  "eligible — no prior reversal in 12 months, fee 7 days old" is evidence, and the reviewer is
  checking the evidence.
- Safety flags with their evidence spans and which detector fired (pattern or model).
- Loop counters, and which loops hit their cap.
- The customer's message and any earlier turns. **Mark `system` turns clearly** — they are
  internal events, not customer speech, and a reviewer skimming will otherwise read
  "Source IP geolocation: inconsistent" as something the customer wrote.

**One thing the screen must get right or the ticket is wrong:** when
`escalation_visible_to_customer` is `False`, the reviewer has to see the referral *and*
understand the draft must not mention it. Render it as a distinct, unmissable banner — not a
field among fields. This is the TCK-1078 case: a third-party access request refused while the
account is quietly referred for abuse review, where naming the referral in the reply warns
exactly the person the account holder may need protecting from.

### 5.2 Queue screen

The pending list, with enough per row to choose what to review next: ticket id, subject,
route, confidence, escalation target, whether any loop capped, and whether the two proposals
disagreed. Filter by route and by "disagreed", sort by confidence ascending — the least
confident decisions are the ones most worth a human's time.

### 5.3 Metrics screen

Read `outputs/reviews.jsonl` and `outputs/audit_logs/*.jsonl`. Show, and label with the mode
that produced them:

- **Edit rate** and **override rate**, the two production quality signals.
- Median edit size, as a proportion of the original draft. A 5% edit and a full rewrite are
  different failures.
- Route distribution and rules-vs-model disagreement rate.
- Confidence calibration: accuracy by confidence decile, if golden labels are available.

Do not compute metrics in the app file, and do not compute anything here that
`src/evaluation/` should own. This screen reads and renders; it does not score.

---

## 6. The six actions and their effects

Take them from `src/hitl/reviewer_actions.py`. Do not re-declare them, and do not add a
seventh without changing that file.

| Action | Effect |
| --- | --- |
| `APPROVE` | Resume; terminates into audit. |
| `APPROVE_AND_ROUTE` | Same, and the escalation target is confirmed. Default when a target exists. |
| `EDIT` | Store `edited_draft` **alongside** the original, resume, terminate. Edit size is a quality signal you cannot compute if you overwrote the thing you would measure against. |
| `REQUEST_REGENERATION` | The only action that re-enters the graph. The reviewer's comment becomes an input to `draft_reply`, which already accepts `reviewer_comment`. The ticket returns to review. |
| `REJECT` | Nothing goes out and nothing is regenerated. Record and terminate; a human takes the ticket over. |
| `ESCALATE_OVERRIDE` | Reviewer escalates a ticket the agent did not. Record the agent's route and the reviewer's, and mark it a route disagreement — `counts_as_route_override` is already `True` on this spec. |

Guard the regeneration loop. `after_review` sends `REQUEST_REGENERATION` back to `draft_reply`,
and `draft_reply` → `validate_draft` → `hitl_gate` returns here. Nothing currently caps how
many times a reviewer may do that. Add a cap in `config/app_config.yaml` alongside the other
three loop caps, enforce it the same way — the node forces the terminal state, the router only
stops looping — and make the UI disable the button once it is reached rather than letting a
click fail.

---

## 7. Traps, named

1. **The node re-runs on resume.** Everything before `interrupt()` executes twice. (§4.1)
2. **`from_conn_string` is a context manager.** Verify and fix. (§4.2)
3. **`check_same_thread=False`** or sqlite refuses the Streamlit worker thread.
4. **`@st.cache_data` on the graph** will try to hash a compiled graph and fail confusingly.
   Use `@st.cache_resource`.
5. **Widget state leaking between tickets.** Stable, ticket-scoped keys.
6. **Rewriting the queue file** to mark items done, which lets it drift from the checkpointer.
   Append a completion record and fold.
7. **Letting `interactive` fall back to `auto`** when nothing is connected. It must fail loudly.
8. **Reducer keys.** If you write to `trace`, `notes`, `loops_capped` or `retrieval_log`, return
   only the delta, never the concatenated whole. A node re-entered by a loop also needs a
   `not in` guard before appending. This has already caused one bug in this repo.
9. **The safety bypass reaches review too.** It arrives with `retrieved == []`, and the review
   screen must handle an empty evidence column without looking broken — that emptiness is
   correct and deliberate, and the screen should say so rather than rendering a blank panel.

---

## 8. Testing

Everything in `src/hitl/` gets real tests. `tests/test_hitl.py`, following the conventions in
the existing suite: short docstrings that say what failure the test prevents, and no test that
needs an API key or a built index. Use the BM25 retriever and `tests/fake_llm.py`, which
already exist for exactly this.

Cover:

- All six actions, each asserting its distinct downstream effect.
- **Restart durability.** Interrupt a graph, discard the in-memory objects, rebuild from the
  sqlite file, resume, and assert the run completes with the pre-interrupt state intact. This
  is the gate; write it first.
- Regeneration re-enters drafting, changes the prompt, and still terminates at `audit_log`.
- An edited draft leaves the original recoverable.
- The queue folds correctly when a ticket is reviewed twice.
- `auto` and `simulate` never call `interrupt()`.
- A silent escalation is flagged to the reviewer and absent from the draft.

For the app file itself, `streamlit.testing.v1.AppTest` can drive it headlessly. Use it for a
smoke test — the app renders, the queue lists, an action fires — and put the real assertions in
the service tests. If a behaviour is hard to test through `AppTest`, that is a sign it belongs
in `review_service.py` instead.

---

## 9. Deliverables

```
app/streamlit_app.py            rendering only
src/hitl/review_service.py      queue, resume, record — all logic
src/hitl/approval_queue.py      append-only pending index
src/graph/nodes.py              hitl_gate rewritten for interrupt/resume
src/graph/support_graph.py      checkpointer fixed
config/app_config.yaml          hitl settings, regeneration cap
requirements.txt                streamlit, langgraph-checkpoint-sqlite
tests/test_hitl.py
docs/human_review.md            one doc, ~250 lines
```

`docs/human_review.md` covers: how to run it, the suspend/resume mechanic and why the node
re-runs, the queue/checkpointer relationship and which wins, the six actions, what the review
screen shows and why the two columns sit side by side, and what is measured. Include the
restart-durability procedure as something the reader can reproduce.

Update `docs/pipeline.md` §8 with the P7 gate result. Do not duplicate the pipeline doc's
content into the new one — link.

---

## 10. Out of scope

Named because HLD §11 already settled them and re-opening one by accident is the risk:

- **No sending, ever.** No email, no CRM write-back, no webhook. The app writes JSONL and
  resumes a graph; that is all.
- **No authentication.** It is a local surface, not a deployment.
- **No multi-user concurrency.** One reviewer. If two processes resume the same thread you get
  undefined behaviour, and solving that properly is a different project.
- **No metrics computation.** `src/evaluation/` owns scoring; the metrics screen reads reports.
- **No new evaluators.** Those are P8.

---

## 11. Definition of done

- [ ] Six actions work, each with its distinct effect, each covered by a test.
- [ ] A ticket paused mid-review survives a full process restart and completes.
- [ ] `auto` and `simulate` are unchanged; the existing 89 tests still pass.
- [ ] `python -m src.main --gate` still green.
- [ ] Silent escalations are unmissable to the reviewer and absent from the draft.
- [ ] Edit rate and override rate are computed from `reviews.jsonl` and displayed.
- [ ] No logic in `app/streamlit_app.py`.
- [ ] `docs/human_review.md` written; `docs/pipeline.md` §8 updated.
- [ ] Every number quoted anywhere states the HITL mode that produced it.

Report what you measured, not what you expect. If the restart test does not pass, say so and
say why — a P7 that half works is more useful known than assumed.
