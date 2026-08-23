# Five-minute demo

A walkthrough a stranger can follow from a clean checkout. Every command below is copy-pasteable
and every number quoted is one this repo printed, with the HITL mode and the model setting that
produced it stated next to it.

The point of the order is that each ticket shows one design decision doing something visible.
Six tickets and a replay.

---

## 0. Setup (once, ~1 minute)

```bash
pip install -r requirements.txt
python -m src.main --gate
```

The gate is the honest opener: it runs offline, needs no API key and no index, and it either
goes green or it does not.

```
[PASS] 150 tickets parse: 150          [PASS] every node reachable: yes
[PASS] 107 golden records parse: 107   [PASS] loop retrieval_refine exits to route_decision
[PASS] P1 doc recall@5 (bm25): 0.92    [PASS] P2 safety-critical flagged: 2/2
                                       [PASS] P2 tone traps not flagged: 6/6
GATE GREEN
```

For the review screens, set the checkpointer once — interactive review refuses to start on
`memory`, on purpose (see `human_review.md` §4):

```yaml
# config/app_config.yaml
graph:
  checkpointer: sqlite
```

**Everything below runs with `--no-model`**, the deterministic layers only: patterns, the rule
engine, BM25 retrieval and the confidence composition. No API key, no torch, no index. Add a
`GROQ_API_KEY` to `.env` and drop the flag to see the model half, and expect different routes — the
deterministic floor escalates anything the rules cannot resolve alone.

---

## 1. TCK-1143 — the happy path *(auto mode, `--no-model`)*

> "Overdraft fee from last Tuesday"

```bash
python -m src.main --ticket TCK-1143 --hitl auto --no-model -v
```

What to point at: the per-node trace. Twelve nodes, one pass each, no loop fired. The fee
clauses come back from BM25, the preconditions compute, the route is decided from *fields*
before anything is drafted — drafting happens after routing on purpose, because a model that
writes something helpful and then reads its own prose concludes AUTO_RESOLVE from its own
fluency.

Measured here: `ESCALATE → Claims Specialist, confidence 0.84, 8 chunks retrieved`. That is the
deterministic floor, not the final answer: with no model there is no second proposal, so
anything the rule engine cannot settle alone escalates. Safe, unhelpful, and zero critical
errors — which is exactly what the 0.447 deterministic route accuracy in `pipeline.md` §8 means.

---

## 2. TCK-1019 — the safety bypass *(auto mode, `--no-model`)*

> "you'll see me at the branch"

```bash
python -m src.main --ticket TCK-1019 --hitl auto --no-model -v
```

This is the one that makes the architecture legible. Look at the trace: `triage → safety_escalate
→ hitl_gate → audit_log`. Four nodes. Retrieval never ran.

Measured: `ESCALATE → Threat Response, confidence 1.00, retrieved 0, retrieval_mode bypassed`.

The empty context is the feature, and it has to be *provable* in the audit record rather than
merely likely. Without the branch, a threat flows down the normal path and gets drafted with fee
clauses sitting in the context window: *"I'm sorry to hear that. Regarding your $35 overdraft
fee, under FEE-001…"*

Note the edge in `edges.py`: `safety_escalate → hitl_gate`. The bypass skips retrieval, not
review.

---

## 3. TCK-1077 — the tone trap *(auto mode, `--no-model`)*

> "I'm going to post this everywhere"

```bash
python -m src.main --ticket TCK-1077 --hitl auto --no-model -v
```

Show it immediately after TCK-1019 and the discrimination becomes obvious. Both are angry. Only
one is a safety case.

Measured: `retrieval_mode bm25, 14 chunks retrieved` — the bypass did **not** fire. The ticket
still routes on the request (a mobile-deposit problem), not on the tone. The branch condition in
`after_triage` is "does a safety-critical flag exist", never "is the customer angry", and six
tickets in the dataset are hostile with a legitimate request underneath.

Measured across the whole set: 2/2 safety-critical flagged, 6/6 tone traps clean, **zero false
positives across all 150**.

The golden label for TCK-1077 is `AUTO_RESOLVE`; deterministic-only gives `ESCALATE`, because
there is no model to propose the resolution. Say so out loud rather than skipping the ticket —
the discrimination on show here is the bypass, not the route.

---

## 4. TCK-1078 — the silent referral *(interactive mode)*

> "need to see my girlfriend's spending"

```bash
python -m src.main --ticket TCK-1078 --hitl interactive --no-model
streamlit run app/streamlit_app.py       # Queue → open TCK-1078
```

Measured: `REFUSE → Conduct Review, escalation_visible_to_customer False`.

Three things are happening at once and the screen has to carry all three:

1. The access request is **refused** — the requester is not the account holder.
2. The account is **referred** for abuse review, because the request pattern is what
   exploitation looks like from the outside.
3. The reply **says nothing about the referral**. Naming it warns exactly the person the account
   holder may need protecting from.

On screen that is a full-width red banner, not a field among fields. Show the banner, then show
that the draft below it does not contain the words "Conduct Review". Then show that the
validator agrees: a draft that *does* name the target fails `validate_draft`.

Contrast it with TCK-1055 ("my daughter has been taking money") if there is time — same family
of signals, opposite handling, because there the customer is the victim asking for help. That
pair is why `FINANCIAL_ABUSE` is deliberately not a bypass code.

---

## 5. TCK-1125 — the escalating thread *(auto mode, `--no-model`)*

> "My attorney is filing with the CFPB tomorrow"

Case history only exists if the earlier tickets ran first, so run the thread in arrival order:

```bash
python -m src.main --all --hitl auto --no-model --limit 150 | grep CUST-0022 -A0
# or, faster, just the four:
python -m src.main --ticket TCK-1044 --hitl auto --no-model
python -m src.main --ticket TCK-1095 --hitl auto --no-model
python -m src.main --ticket TCK-1109 --hitl auto --no-model
python -m src.main --ticket TCK-1125 --hitl auto --no-model
```

Measured, in that order:

| Ticket | Route | Target | Thread pressure |
| --- | --- | --- | --- |
| TCK-1044 dispute denied | ESCALATE | Claims Specialist | 0 |
| TCK-1095 close my account | ESCALATE | Account Review | 1 |
| TCK-1109 name the rep who handled it | **REFUSE** | Conduct Review | 2 |
| TCK-1125 my attorney is filing | ESCALATE | **Executive Complaints** | 2 |

Two things to point at.

TCK-1125 does not go back to Claims Specialist — the queue that produced the denial being
complained about. That is how a complaint becomes a regulatory filing.

And TCK-1109 has the same pressure level 2 and stays **REFUSE**. Pressure *hardens* routing; it
never overrides it. The naive rule — "a repeat contact escalates" — breaks this ticket and
breaks TCK-1142 (a genuine new request that stays AUTO_RESOLVE) in the opposite direction.

In the review screen, the prior three tickets appear on the right with the pressure level and
its reason, which is the whole argument for showing history to a human: read alone, TCK-1125 is
a moderately angry customer.

---

## 6. A disagreement *(needs a key)*

The one thing the deterministic run cannot show. With no model there is no `llm_route`, so the
two proposals can never differ — the disagreement rate on a `--no-model` run is 0 by
construction, not by agreement.

```bash
cp .env.example .env                  # then set GROQ_API_KEY=gsk_...
python -m src.main --sample --hitl interactive
streamlit run app/streamlit_app.py    # Queue → tick "Only where the rules and the model disagreed"
```

The queue sorts least-confident first and filters on disagreement, because those are the
decisions most worth a human's time. Open one: the right column says so in red, naming both
proposals. When the halves disagree the route holds at ESCALATE while the confidence loop
reconsiders — a disagreement is a signal to look again, not a verdict.

Then act on it. `ESCALATE_OVERRIDE` records the agent's route *and* the reviewer's rather than
replacing one with the other, and the Metrics screen picks it up as override rate, labelled with
the mode that produced it.

---

## 7. The replay — the whole decision, without re-running anything

```bash
python -m src.logging.replay --latest --ticket TCK-1125
python -m src.logging.replay --latest --check
```

The test of sufficiency is a question: *could you defend this decision six months from now,
without re-running the agent?* `--check` turns it into an exit code.

Measured over the full 150-ticket run: **150/150 replayable**.

Read the output top to bottom and it replays the decision in the order it was made — what we
already knew about the customer, triage, the computed facts *with their inputs*, every retrieval
attempt and its query, both route proposals, the confidence and its components, the reply, and
the review. A precondition without its inputs is a verdict, not evidence, and `missing_evidence`
fails a record that carries one.

---

## What was on screen, and in which mode

| Shown | Mode | Model |
| --- | --- | --- |
| §1–§3, §5 routes, targets, confidences | `auto` | none (`--no-model`) |
| §4 silent referral, review screen | `interactive` | none (`--no-model`) |
| §6 disagreement, override rate | `interactive` | Groq key required |
| §7 replay, 150/150 | scored offline from `auto`-mode audit records | none |

The distinction is not pedantry. An `auto`-mode approval is not evidence about what a human
would have done, and a route accuracy measured without a model is the floor rather than the
result. `pipeline.md` §8 carries the full table.
