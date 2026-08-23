# LLD notes — parking lot

> **Status: raw notes, not decisions.** This file holds low-level design material drafted
> alongside the HLD on 2026-08-13, before any code existed. Every number in it is a first
> guess, not a measurement.
>
> The plan (HLD §10) is to write a proper LLD per subsystem at the start of its phase, when
> parameters can come from measurement. When that happens, the relevant section here is
> **superseded and should be deleted**, not left to rot alongside the real one.
>
> Read [`architecture.md`](architecture.md) first. Where the two disagree, the HLD wins.

---

> ### Superseded sections have been deleted
>
> | Was | Now lives in | Deleted |
> | --- | --- | --- |
> | §1 Graph topology at node level | `pipeline.md` §2 and §3 | 2026-08-20 |
> | §2 Graph state | `src/graph/graph_state.py` | 2026-08-20 |
> | §9 Config keys | the three files in `config/`, which now carry their own rationale | 2026-08-20 |
> | §10 Folder structure | `pipeline.md` §7 — realised on disk | 2026-08-20 |
>
> §3 (retrieval parameters) is **also superseded**, by `lld_p1_retrieval.md`, and should go the
> next time you touch retrieval. It is left for now only because `lld_p1_retrieval.md` §4 and §6
> reference it by number; move those references first, then delete it.
>
> §4 (analyse_policy contract), §5 (route reconciliation) and §6 (confidence formula) are now
> **implemented** -- see `src/agents/policy.py`, `src/graph/nodes.route_decision` and
> `src/routing/confidence.py`, with the reasoning in `pipeline.md` §3 and §5. Delete them here
> once you have checked the code matches.
>
> §7, §8, §11 and §12 are still parking-lot material, for P6 and P8.

---

## 3. Retrieval parameters

All provisional; sweep in P1.

| Setting | First guess | Note |
| --- | --- | --- |
| Embedding model | `BAAI/bge-small-en-v1.5` | 384-dim, local, free |
| Chunking | One chunk per `###` clause; 800-token ceiling, 75-token overlap on overflow | ~59 clause + ~15 structural ≈ 75 chunks |
| Embedded text | `{doc_title}\n{scope_note}\n### {policy_id} — {title}\n{body}` | Prepending the scope note makes *absence* of coverage retrievable |
| `k` | 5 dense, plus the guaranteed set | Brief says 3–5 |
| Similarity floor | 0.35 cosine | **Sweep against the 8 no-policy tickets.** Too low and absence is never detected; too high and easy tickets escalate |
| Index refresh | Content-hash per file, skip unchanged | The KB is hand-edited source; expect frequent re-indexing |

**Query construction.** Do not embed the raw message — a 400-word all-caps rant embeds to a
vector dominated by outrage. Build the query from `subject` + triage's extracted intent and
entities + `product_area`. The raw message is for reasoning only.

**Guaranteed context** (from `routing_rules.yaml`, injected regardless of similarity):

| Condition | Always inject |
| --- | --- |
| Any ticket | `CON-010`, `CON-011` |
| `sentiment ∈ {angry, distressed}` | `CON-001`, `CON-002` |
| `category == conduct_and_prohibited` | all `CON-*` |
| `category == disputes_and_fees` | `DSP-006` |
| `product_area == digital_access` | `ACC-007`, `ACC-010` |

`CON-011` in context on every ticket costs ~150 tokens and is the cheapest available defence
against the tone traps.

**Do not cite guaranteed-context clauses to customers.** `CON-010` is the only one of the 59
that appears in the golden set's grounding claims but never in any ticket's
`expected_policy_ids` — it is an internal drafting standard. Quoting it at a customer is both
a citation error and a bad reply.

**Absence detection** needs two of three signals: top-1 below floor after both attempts; the
retrieved scope-note chunk names the topic as out of scope; analysis reports no deciding
clause. Then `ESCALATE` **and** the draft must carry the unverifiable-policy statement —
escalating without that sentence scores as wrong on those 8 tickets.

---

## 4. `analyse_policy` output contract

Structured, no prose. Separating *deciding* from *constraining* clauses is what makes
conflicting-guidance tickets tractable.

```json
{
  "deciding_clauses": [{"policy_id": "DSP-003", "why": "re-opened claim after denial"}],
  "constraining_clauses": [{"policy_id": "DSP-006",
                            "constraint": "must not explain how 'verified' was determined"}],
  "missing_facts": [],
  "policy_verified": true,
  "conflicts": [{"between": ["DSP-003", "DSP-006"],
                 "resolution": "escalate without explaining verification logic"}],
  "self_certainty": 0.7
}
```

`missing_facts` drives `ASK_MORE_INFO` and must be **validated against the ticket text** before
it can do so. Several tickets supply date, amount and merchant and are still `ASK_MORE_INFO`,
because the genuinely missing fact is something else — whether the merchant was contacted,
whether an entry is still pending. Re-asking for what is already there is its own failure mode.

---

## 5. Route reconciliation

```
rule_route  ← routing_rules.yaml fired against preconditions + safety_flags + category
llm_route   ← structured call over policy_analysis + preconditions + retrieved chunks

if safety-critical flag        → ESCALATE  (rules win outright, no model involvement)
elif not policy_verified       → ESCALATE  (rules win outright)
elif rule_route == llm_route   → that route, confidence bonus
elif rule_route is None        → llm_route (no rule covers this ticket)
else                           → disagreement: record both, confidence penalty,
                                 re-check loop; if unresolved → ESCALATE
```

---

## 6. Confidence formula

Provisional weights. Fit against the 107 golden bands in P5 and record what moved.

```
confidence = 0.30 · retrieval_strength       # normalised top-1, ≥1 clause chunk present
           + 0.25 · clause_coverage          # decides it 1.0 / partially 0.5 / none 0.0
           + 0.20 · precondition_determinacy # needed context fields present, unambiguous
           + 0.15 · route_agreement          # rule_route == llm_route → 1.0
           + 0.10 · self_certainty           # the model's own number, capped at 10%
```

Route floors, initialised from the golden bands:

| Route | Band | Golden records |
| --- | --- | --- |
| `AUTO_RESOLVE` | 0.80 – 1.00 | 30 |
| `REFUSE` | 0.75 – 1.00 | 17 |
| `ESCALATE` | 0.55 – 0.95 | 46 |
| `ASK_MORE_INFO` | 0.30 – 0.70 | 14 |

---

## 7. Audit record fields

`outputs/audit_logs/run_{run_id}.jsonl`, append-only, one record per ticket:

`run_id` · `ticket_id` · timestamps · config and prompt hashes · model IDs per node ·
`sentiment` · safety flags with evidence spans · every retrieval attempt (query, chunk IDs,
scores, policy IDs) · computed preconditions **with their inputs** · `rule_route` · `llm_route`
· final route + rationale · escalation target + visibility · confidence + components · all
three loop counters · draft text · cited policy IDs · validation result · reviewer action and
comments · tokens and latency per node.

---

## 8. Evaluators

`src/evaluation/`, each writing JSON + Markdown to `outputs/evaluation_reports/`.

| Evaluator | Measures | Golden field |
| --- | --- | --- |
| `route_accuracy_eval` | Overall, per-route P/R, 4×4 confusion matrix, **hard subset separately**, escalation-target accuracy | `expected_route`, `expected_escalation_target`, `difficulty` |
| `groundedness_eval` | Each required claim supported by the **retrieved chunks**. Two scores: mechanical (is the ID in the retrieved set) and judged (entailment against retrieved text) | `grounding_claims_required` |
| `citation_eval` | Cited ⊆ expected; **cited but not retrieved = hallucinated, hard failure**; constraint-only clauses cited = error | `expected_policy_ids` |
| `retrieval_eval` | Document recall@k, and clause-level recall | `expected_kb_sources`, `expected_policy_ids` |
| `safety_eval` | Prohibited-content scan — regex for literal items, judge for semantic ones | `must_not_contain` |
| `confidence_eval` | In-band rate; accuracy by confidence decile; did the loop fire when it should have | `expected_confidence_band` |
| `no_policy_eval` | Escalated **and** stated policy unverifiable. Both required | `no_policy_in_kb` |

Phoenix setup, deliberately minimal:

```bash
pip install arize-phoenix openinference-instrumentation-langchain
phoenix serve                                    # UI on localhost:6006
```

```python
from phoenix.otel import register
register(project_name="support-ticket-agent", auto_instrument=True)
```

LangGraph runs on LangChain callbacks, so the LangChain instrumentor captures every node, model
call and retrieval span with no further work. Phoenix *experiments* over the golden set are a
stretch goal, after the custom evaluators work.

---

## 11. Worked trace — `TCK-1143`

The easiest possible ticket, end to end, to make the tables above legible. Expected:
`AUTO_RESOLVE`, `easy`, band `[0.80, 1.00]`, reviewer `APPROVE`.

> *"I got hit with a $35 overdraft fee on 8/4. My rent auto-payment cleared the same morning my
> paycheck was supposed to land and the paycheck came in about six hours later. I've been with
> Northgate since 2019 and I don't think I've ever asked for anything like this before."*

| Node | Output |
| --- | --- |
| `triage` | `sentiment: neutral`; no safety flags; `intent: "overdraft fee reversal request"`; `entities: {fee_type: overdraft, amount: 35, fee_date: 2026-08-04}` |
| `preconditions` | `prior_fee_reversals_12m = 0` ✓ · fee age 7 days < 60 ✓ · `tenure_months = 79` ✓ · fee type eligible ✓ · `segment: Consumer` ✓ → **`FEE-001: ALL MET`**, `FEE-002: N/A` |
| `retrieve` | `FEE-001` (0.79), `FEE-006` (0.61), `FEE-002` (0.58), fee-limits table (0.52), `TRB-007` (0.41); guaranteed `CON-010`, `CON-011`, `DSP-006` |
| `analyse_policy` | deciding `FEE-001`; constraining `DSP-006`; `missing_facts: []`; `policy_verified: true`; `self_certainty: 0.85` |
| `route_decision` | `rule_route = llm_route = AUTO_RESOLVE` → agree. No target |
| `score_confidence` | `0.30(0.79) + 0.25(1.0) + 0.20(1.0) + 0.15(1.0) + 0.10(0.85) = 0.92` ≥ 0.80 floor → no loop |
| `draft_reply` | One-time courtesy reversal under `FEE-001`, up to $140, posting in 1–2 business days, once per 12 months. Cites `FEE-001`. No outcome promise beyond the clause (`DSP-006`) |
| `validate_draft` | `FEE-001` ∈ retrieved ✓ · no prohibited content ✓ · "1–2 business days" verbatim in the `FEE-001` chunk ✓ |
| `hitl_gate` | Reviewer sees draft + five chunks + `FEE-001: ALL MET` with inputs → `APPROVE` |
| `audit_log` | Record written; thread store updated for `CUST-0001` |

Now flip one field — `prior_fee_reversals_12m: 1` — and the customer's message is unchanged, but
`FEE-001` becomes unmet, `FEE-002` applies, `rule_route` becomes `ESCALATE → Service Recovery`,
and if the model still says `AUTO_RESOLVE` because it believed *"I don't think I've ever asked
before"*, the disagreement penalty drops confidence below 0.80 and the re-check loop fires.

That contrast is HLD D2 and D4 in a single ticket. Worth stepping through by hand before writing
any code.

---

## 12. Parameters to sweep

Tracked here rather than in the HLD, because these are expected to change:

1. **Confidence weights** (§6) — fit against the 107 golden bands at P5.
2. **Similarity floor** (§3) — sweep against the 8 no-policy tickets at P1.
3. **`k`** — 5 is the brief's ceiling; test whether the guaranteed set makes a smaller dense `k`
   viable.
4. **Chunk ceiling** — 800 tokens; check how many of the 59 clauses actually overflow. If none
   do, the recursive splitter is dead code and the overlap parameter is moot.
