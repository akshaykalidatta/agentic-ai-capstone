# Human review (P7)

The gate a reply passes through before anyone could send it, and the surface a person uses to
judge it. `pipeline.md` is how the agent decides; this is how a human checks the decision.

---

## 1. Run it

Interactive review needs a durable checkpointer, so set it once:

```yaml
# config/app_config.yaml
graph:
  checkpointer: sqlite        # 'memory' dies with the process; see §4
```

Then:

```bash
pip install -r requirements.txt                    # adds langgraph-checkpoint-sqlite, streamlit
python -m src.main --sample --hitl interactive     # 13 tickets, each stops at the review gate
streamlit run app/streamlit_app.py                 # the surface, on localhost:8501
```

The sidebar can also queue tickets itself, which is the shorter path for a demo. Either way the
pending set lands in `outputs/approval_queue.jsonl` and every decision in
`outputs/reviews.jsonl`.

Nothing here sends anything. There is no email, no CRM write-back and no webhook — a reviewed
draft is a recorded decision and nothing else (HLD §11).

---

## 2. What the gate is for

Three things are architectural, not preferences, and undoing any of them changes what the
project measures.

**Review is a gate, not a notification.** Every path reaches `hitl_gate`, including the safety
bypass. `safety_escalate → hitl_gate` is a real edge in `edges.py`, so a crisis ticket is
reviewed like any other — it simply arrives with no retrieved evidence, which is the branch
working (§6).

**The reviewer sees the clauses beside the draft.** A reviewer shown only the draft is judging
fluency. One who can see what the agent read is judging groundedness, which is the thing that
matters — and it makes them the ground truth for the groundedness metric rather than another
opinion about it. That is why the review screen is two columns and why the left one is not
collapsible.

**Three modes, never silently interchangeable.**

| Mode | Who decides | What it is for |
| --- | --- | --- |
| `auto` | the code, always approve | 150 tickets end to end with no human in the loop |
| `simulate` | the golden set's `expected_reviewer_action` | replaying labelled review decisions |
| `interactive` | a person | this phase |

`interactive` never falls back to `auto`. `ReviewService.require_durable_checkpointer` raises
`InteractiveReviewUnavailable` rather than running the batch path, because a fallback would let
someone publish an "interactive" edit rate that no human ever produced.

---

## 3. Suspend and resume, and why the node runs twice

`hitl_gate` in interactive mode calls LangGraph's `interrupt()`:

```python
submitted = interrupt(review_payload(state)) or {}
```

`interrupt()` **raises** on the first pass. LangGraph catches that, writes a checkpoint, and
`invoke` returns with the run suspended. The app later resumes it:

```python
graph.invoke(Command(resume={"action": "APPROVE", ...}), config={"configurable": {"thread_id": ...}})
```

On resume **the node re-executes from the top**. `interrupt()` does not raise the second time;
it returns the value `Command(resume=...)` carried.

That re-execution is the trap the whole node is shaped around. Everything above the
`interrupt()` line happens twice, so it has to be pure:

- `review_payload(state)` only reads state — it is in `graph_state.py` next to `summarise` for
  exactly that reason.
- Nothing above the line writes a file, increments a counter or logs a first occurrence.
- Every write in `hitl_gate` — the `ReviewerDecision`, the override note, the regeneration
  counter — is below the line, in the update the node returns.

One consequence that is easy to miss: `@traced` wraps every node and catches `Exception` to log
a failure. A suspension comes out of the node body as an exception, so `trace_logger` now checks
the MRO for `GraphInterrupt`/`GraphBubbleUp` and re-raises without logging. Matched by class
name, not by import, so `trace_logger` stays importable with no langgraph installed — which is
what lets `tests/test_graph_topology.py` run on a bare checkout.

`auto` and `simulate` never touch `interrupt()`. They are ordinary nodes, and one that suspended
would hang every eval run waiting for a person who is not there.
`test_auto_and_simulate_never_interrupt` installs a sentinel that makes that failure loud.

---

## 4. Checkpointing and thread identity

Durability across a restart is entirely the checkpointer's job.

```yaml
graph:
  checkpointer: sqlite
  sqlite_path: outputs/checkpoints.sqlite
```

`memory` dies with the process. For a suspended review that means the queue file points at
threads that no longer exist anywhere, so P7 requires `sqlite`. The default is left on `memory`
because batch runs do not need durability and a 150-ticket run should not leave a checkpoint
database behind — and the requirement is enforced by a loud check rather than by forcing sqlite
silently, so `app_config.yaml` never disagrees with what actually ran.

Building the saver is three decisions, all in **`src/graph/checkpointing.py`** — one module, used
by `support_graph._default_checkpointer` *and* by `tests/test_hitl.py`, so a saver that only
works in the tests is not a way the gate can pass:

- `SqliteSaver.from_conn_string` is a `@contextmanager` in recent versions. Returning it hands
  back a context-manager object and the graph fails on first write, so the saver owns its own
  `sqlite3.connect`.
- `check_same_thread=False`, because Streamlit resumes from a worker thread that is not the one
  that opened the connection.
- **The metadata serializer is repaired when the installed packages disagree.**
  `langgraph-checkpoint` 4.x keeps only the typed `dumps_typed`/`loads_typed` on
  `JsonPlusSerializer`; `langgraph-checkpoint-sqlite` still calls the untyped `dumps`/`loads` on
  the metadata column, so on that pairing every `put()` raises `AttributeError` and no review
  reaches disk. `JsonMetadataSerializer` fills the hole with JSON — JSON specifically, because
  the saver's own filter compiles to `json_extract(CAST(metadata AS TEXT), '$.key')`, and any
  other encoding would write, resume, and then match nothing on `list(filter=...)`. The repair
  is conditional on the attribute being absent, so a matched pair of packages keeps its own
  serializer and the shim becomes a no-op rather than something to remember to remove.

Metadata is the filter index, never the source for a resume: the state itself is the checkpoint
blob, which still goes through `dumps_typed`. That is why a value JSON cannot encode is allowed
to degrade to its repr instead of failing the save.

**Thread identity is `f"{run_id}:{ticket_id}"`** — the format `main.py` already used. It matters
that it reconstructs from a queue entry alone (`QueueEntry.thread_id`): nothing about resuming a
review depends on an object that lived in the previous process, which is what makes a restart
recoverable rather than merely survivable.

---

## 5. The queue and the checkpointer — which one wins

Two sources answer "what is waiting for a human", and both are needed:

| Source | Answers | Cost |
| --- | --- | --- |
| the checkpointer | is *this* thread suspended? | authoritative, but you need the thread id first |
| `outputs/approval_queue.jsonl` | which threads are there? | enumerable, but only as true as its last write |

The queue file is **append-only**. A completion is another line, and the pending set is a fold
over the whole file: a ticket sent back for regeneration and then approved writes
queued / reviewed / queued / reviewed and folds to nothing. Rewriting the file to delete a line
would let it drift from the checkpointer, and the checkpointer is the one that is right.

So when they disagree, the surface says so. `ReviewService.pending()` labels every entry
`suspended`, `not_suspended` or `missing`, the queue screen shows a warning naming the drifted
threads, and only the ones the checkpointer agrees are suspended can be opened. Guessing which
source to believe would produce a resume that fails halfway.

---

## 6. What the review screen shows

Two columns. The adjacency is the requirement.

### Left — what the agent read

Every chunk with its policy ID, source file, chunk type and similarity, and whether it was
retrieved or injected as guaranteed context. Chunks with `citable=False` are labelled
**INTERNAL** and carry a red note: CON-010 is a drafting standard written for staff, and
quoting it at a customer is both a citation error and a strange reply.

Below the chunks, every retrieval attempt with its query, top similarity, whether it fell below
the floor and whether the scope signal fired — so a reviewer looking at thin evidence can see
what was actually asked for.

Then the ticket, with **`system` turns marked as internal events**. They are facts to reason
from, not customer speech, and a reviewer skimming reads "Source IP geolocation: inconsistent"
as something the customer wrote unless the screen says otherwise.

**An empty panel is sometimes correct.** A safety-critical ticket arrives with `retrieved == []`
by design, and the screen says so in as many words instead of rendering a blank box that looks
broken. TCK-1019 is the one to look at.

### Right — what the agent decided and wrote

Route, target, confidence with its five components broken out, and the rationale.

**Both proposals, side by side.** When `rule_route` and `llm_route` disagree the screen says so
loudly, because that disagreement is this design's hard-case detector (HLD D4) and it is the
most useful thing a reviewer can be told. `None == None` is not agreement and is not reported as
one.

**Preconditions with their inputs.** "Eligible" is an assertion; "eligible — no prior reversal
in 12 months, fee 7 days old" is evidence, and the reviewer is checking evidence.

Safety flags with their evidence span and which detector fired; the loop counters and which
loops capped; and, when the customer has written before, the prior tickets with the thread
pressure level and the reason for it. TCK-1125 is the fourth contact in an escalating story and
reads completely differently with that context.

### The one thing the screen must not get wrong

When `escalation_visible_to_customer` is `False` the reviewer sees a full-width red banner, not
a field among fields:

> **🔇 SILENT REFERRAL — Conduct Review.** This case is being referred internally and the reply
> must not mention it.

This is TCK-1078 — a third-party access request refused while the account is quietly referred
for abuse review. Naming the referral in the reply warns exactly the person the account holder
may need protecting from. The validator already fails a draft that names the target
(`validate_draft`); the banner is what stops a reviewer *approving* one.

---

## 7. The six actions

Taken from `src/hitl/reviewer_actions.py`, which is the single definition all three consumers
read — `edges.after_review`, the audit record, and this screen.

| Action | Effect |
| --- | --- |
| `APPROVE` | Resume; terminate into audit. |
| `APPROVE_AND_ROUTE` | Same, target confirmed. Offered first whenever a target exists. |
| `EDIT` | Stores `edited_draft` **alongside** the original. |
| `REQUEST_REGENERATION` | The only re-entry. The comment reaches `draft_reply`'s prompt. |
| `REJECT` | Nothing out, nothing regenerated. Recorded and terminated. |
| `ESCALATE_OVERRIDE` | The agent's route and the reviewer's, marked a disagreement. |

Two of those hide a decision worth knowing about.

**`EDIT` does not overwrite `state["draft"]`.** Edit size is a quality signal you cannot compute
once you have overwritten the thing you would measure against, so the agent's text stays in
`draft` and the reviewer's lands in `reviewer.edited_draft`. Nothing is ever sent, so there is
no "final" copy that has to be authoritative.

**`ESCALATE_OVERRIDE` does not rewrite the route either.** The audit record answers *what did
the agent decide*, and rewriting `state["route"]` would quietly move every overridden ticket out
of the route-accuracy denominator. The override is recorded in `reviews.jsonl` with both routes
and `route_override: true`.

`REQUEST_REGENERATION` is capped by `graph.loop_caps.review_regeneration` (3), enforced exactly
like the other three loops: the node writes the counter and records `loops_capped`, the router
only stops looping. The button is removed at the cap rather than left to fail on click.

---

## 8. What is recorded

`outputs/reviews.jsonl`, one line per decision — separate from the audit log because the audit
log is per run and this is per decision. A ticket regenerated once and then approved has **one**
audit record and **two** review records.

Each line carries `run_id`, `ticket_id`, `action`, `comments`, `reviewed_at`, `reviewer`, `mode`,
the original `draft`, the `edited_draft` when there is one and its `edit_size`, the agent's route
and target, the reviewer's route and target when overridden, both proposals, and the confidence.

The write order is deliberate: the graph resumes first, and the review is only recorded once it
has actually run. The reverse leaves `reviews.jsonl` claiming a review the run never saw.

---

## 9. What is measured

The metrics screen reads `outputs/reviews.jsonl` and calls `src.evaluation.report.build` for
everything else. It computes nothing that `src/evaluation/` owns, and it recomputes nothing.

**Every figure is split by HITL mode and never pooled.** An `auto`-mode approval is not evidence
about what a human would have done; averaging the two produces a number that describes neither.

| Signal | Definition |
| --- | --- |
| edit rate | `EDIT` decisions / decisions in that mode |
| override rate | decisions whose action `counts_as_route_override` / decisions |
| median edit size | changed characters as a proportion of the original, over edited drafts only |
| disagreement rate | decisions where the two proposals differed |
| route distribution | the agent's route, counted |

Every one of them is shown with its `n`. A rate without its denominator cannot be told apart
from a rate over nothing — the exact failure that let three evaluator tests in this repo pass on
an empty set before it was caught.

Median edit size is deliberately uncapped: a reviewer who wrote three times as much scores above
1.0, and clamping that to "completely rewritten" hides the difference between a rewrite and a
rewrite that also had to explain itself.

---

## 10. Where the code lives

```
app/streamlit_app.py            rendering only — no decisions, no metrics, no file writes
src/hitl/review_service.py      the adapter: queue, resume, record, measure. All logic.
src/hitl/approval_queue.py      append-only pending index
src/hitl/reviewer_actions.py    the six actions as data (P0)
src/graph/graph_state.py        review_payload() — what the reviewer is shown
src/graph/nodes.py              hitl_gate — interrupt / resume
```

Dependency direction is `app/` → `src/hitl/` → `src/graph/`, and it does not run back:
`review_payload` lives in `graph_state.py` rather than in the service precisely so that
`hitl_gate` can build it without `src/graph/` importing `src/hitl/`.

The app file is a view because Streamlit re-executes the whole script on every widget
interaction — logic there runs an unpredictable number of times — and because a Streamlit script
is awkward to test while a service module is not. Concretely that means `@st.cache_resource`
for the compiled graph and its sqlite connection (never `@st.cache_data`, which tries to hash
and copy what it caches), an explicit ticket-scoped `key` on every widget, and `st.rerun()`
after an action rather than mutating the rendered page.

`review_service.py` replaces the `approval_ui_stub` the early LLD notes parked here. **It is the
real adapter, not a stub** — calling it one would tell the next reader the wrong thing about
where the logic lives.

---

## 11. Restart durability — reproduce it yourself

The phase gate. `tests/test_hitl.py::test_a_suspended_review_survives_a_process_restart` is the
automated version; this is the same thing by hand.

```bash
# 1. set graph.checkpointer: sqlite, then suspend a ticket
python -m src.main --ticket TCK-1143 --hitl interactive
#    -> TCK-1143 ... AWAITING REVIEW

# 2. confirm it is on disk and nowhere else
cat outputs/approval_queue.jsonl        # one 'queued' line
ls -l outputs/checkpoints.sqlite

# 3. the restart: nothing from step 1 is running any more
streamlit run app/streamlit_app.py
#    -> Queue screen lists TCK-1143, checkpoint 'suspended'
#    -> open it: the draft, the clauses and the confidence are the ones from step 1
#    -> approve it

# 4. it completed, and the record proves it
tail -1 outputs/reviews.jsonl
python -m src.logging.replay --latest --ticket TCK-1143
```

If step 3 shows the ticket with checkpoint `missing`, the checkpointer was `memory` when step 1
ran. That is the failure this section exists to make visible rather than mysterious.

---

## 12. Out of scope

Settled in HLD §11, listed because re-opening one by accident is the risk.

- **No sending, ever.** No email, no CRM write-back, no webhook.
- **No authentication.** A local surface, not a deployment.
- **No multi-user concurrency.** One reviewer. Two processes resuming one thread is undefined,
  and nothing here tries to make it defined.
- **No metric computation in the UI.** `src/evaluation/` owns scoring.
