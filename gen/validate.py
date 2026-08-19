# -*- coding: utf-8 -*-
"""Integrity checks for the generated data/ folder.

Run after gen/generate.py. Exits non-zero on any failure.

    python gen/validate.py
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
KB = DATA / "knowledge_base"
ROUTES = {"AUTO_RESOLVE", "ESCALATE", "REFUSE", "ASK_MORE_INFO"}
PRIORITIES = {"low", "medium", "high", "urgent"}
DIFFICULTIES = {"easy", "moderate", "hard"}

KB_FILES = [
    "refund_policy.md",
    "account_access_faq.md",
    "subscription_policy.md",
    "abusive_content_policy.md",
    "troubleshooting_faq.md",
]

fails: list[str] = []
warns: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        fails.append(msg)


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- knowledge base
kb_text = {}
defined_ids: set[str] = set()
for name in KB_FILES:
    path = KB / name
    check(path.exists(), f"missing KB file: {name}")
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8")
    kb_text[name] = text
    check(len(text) > 4000, f"{name} is thin ({len(text)} chars) for a real-world policy doc")
    check(text.startswith("# "), f"{name} does not start with an H1 title")
    check("Scope note" in text or "Scope note." in text or "scope" in text.lower(),
          f"{name} has no scope statement")
    # A policy ID is 'defined' where it appears as a heading, e.g. '### FEE-001 -- ...'
    for m in re.finditer(r"^#{2,4}\s+([A-Z]{3}-\d{3})\b", text, re.M):
        defined_ids.add(m.group(1))

check(len(defined_ids) >= 45, f"only {len(defined_ids)} policy IDs defined across the KB")

# ---------------------------------------------------------------- tickets
tk_doc = load(DATA / "tickets" / "synthetic_tickets.json")
tickets = tk_doc["tickets"]
check(len(tickets) == tk_doc["record_count"] == 150, "ticket count is not 150")
check(tk_doc.get("synthetic") is True, "tickets file is not flagged synthetic")

ids, cust_ids = set(), set()
for t in tickets:
    tid = t["ticket_id"]
    check(re.fullmatch(r"TCK-\d{4}", tid) is not None, f"bad ticket_id format: {tid}")
    check(tid not in ids, f"duplicate ticket_id: {tid}")
    ids.add(tid)
    cust_ids.add(t["customer_id"])

    for field in ("ticket_id", "customer_id", "subject", "message", "conversation_history",
                  "priority", "created_at", "channel", "category", "product_area", "tags",
                  "customer_context", "sla"):
        check(field in t, f"{tid} missing required field {field}")

    check(t["priority"] in PRIORITIES, f"{tid} bad priority {t['priority']}")
    # A handful of one-line messages are deliberate -- they are what forces ASK_MORE_INFO.
    check(len(t["message"]) >= 10, f"{tid} message suspiciously short")
    check(t["subject"].strip() == t["subject"], f"{tid} subject has stray whitespace")

    created = datetime.fromisoformat(t["created_at"])
    for turn in t["conversation_history"]:
        for f in ("turn", "role", "timestamp", "text"):
            check(f in turn, f"{tid} history turn missing {f}")
        check(datetime.fromisoformat(turn["timestamp"]) < created,
              f"{tid} history turn is not before created_at")
        check(turn["role"] in {"customer", "agent", "system"},
              f"{tid} bad history role {turn['role']}")
    turns = [x["turn"] for x in t["conversation_history"]]
    check(turns == sorted(turns), f"{tid} history turns out of order")

    fr = datetime.fromisoformat(t["sla"]["first_response_due_at"])
    res = datetime.fromisoformat(t["sla"]["resolution_due_at"])
    check(created < fr <= res, f"{tid} SLA clocks are inconsistent")

    for rel in t.get("related_tickets", []):
        check(datetime.fromisoformat(rel["created_at"]) < created,
              f"{tid} related ticket {rel['ticket_id']} is not earlier")

# A ticket must not arrive before an event its own message describes.
MONTHS = {m: n for n, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}
MONTHS.update({m[:3]: n for m, n in list(MONTHS.items())})
_MD_WORD = re.compile(r"\b(" + "|".join(MONTHS) + r")\.?\s+(\d{1,2})\b", re.I)
_MD_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")

for t in tickets:
    created = datetime.fromisoformat(t["created_at"])
    refs = [(MONTHS[m.lower()], int(d)) for m, d in _MD_WORD.findall(t["message"])]
    refs += [(int(a), int(b)) for a, b in _MD_SLASH.findall(t["message"])
             if 1 <= int(a) <= 12 and 1 <= int(b) <= 31]
    for month, day in refs:
        try:
            ref = datetime(2026, month, day, tzinfo=created.tzinfo)
        except ValueError:
            continue
        if ref > datetime(2026, 8, 12, 23, 59, tzinfo=created.tzinfo):
            continue
        check(ref.date() <= created.date(),
              f"{t['ticket_id']} references {ref.date()} but arrived {created.date()}")

# messages must be genuinely distinct, not templated
msgs = [t["message"] for t in tickets]
check(len(set(msgs)) == 150, "duplicate ticket messages found")
subs = [t["subject"] for t in tickets]
check(len(set(subs)) == 150, "duplicate ticket subjects found")

# no obviously real-looking PII patterns
pii = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b(?:\d[ -]?){15,16}\b")
for t in tickets:
    check(pii.search(t["message"]) is None, f"{t['ticket_id']} message may contain an SSN/PAN pattern")

# ordering
stamps = [datetime.fromisoformat(t["created_at"]) for t in tickets]
check(stamps == sorted(stamps), "tickets are not ordered by created_at")

# ---------------------------------------------------------------- sample batch
sm = load(DATA / "tickets" / "sample_ticket_batch.json")
sample = sm["tickets"]
check(len(sample) == sm["record_count"], "sample batch count mismatch")
by_id = {t["ticket_id"]: t for t in tickets}
for t in sample:
    check(t["ticket_id"] in by_id, f"sample ticket {t['ticket_id']} not in parent dataset")
    check(t == by_id[t["ticket_id"]], f"sample ticket {t['ticket_id']} diverges from parent record")

# ---------------------------------------------------------------- expected routes
er = load(DATA / "evaluation" / "expected_routes.json")
labels = er["labels"]
check(set(labels) == ids, "expected_routes labels do not match the ticket set exactly")
dist = {}
for tid, lab in labels.items():
    check(lab["route"] in ROUTES, f"{tid} bad route {lab['route']}")
    check(lab["difficulty"] in DIFFICULTIES, f"{tid} bad difficulty {lab['difficulty']}")
    if lab["route"] == "ESCALATE":
        check(bool(lab["escalation_target"]), f"{tid} escalates with no target")
    if lab["route"] == "AUTO_RESOLVE":
        check(lab["no_policy_in_kb"] is False, f"{tid} auto-resolves with no policy support")
    dist[lab["route"]] = dist.get(lab["route"], 0) + 1

check(sum(dist.values()) == 150, "route distribution does not sum to 150")
for route in ROUTES:
    check(dist.get(route, 0) >= 15, f"route {route} is under-represented ({dist.get(route, 0)})")

hard_n = sum(1 for l in labels.values() if l["difficulty"] == "hard")
check(40 <= hard_n <= 50, f"hard-case share is {hard_n}/150, outside the intended ~30%")

nopol = [tid for tid, l in labels.items() if l["no_policy_in_kb"]]
check(len(nopol) >= 7, f"only {len(nopol)} no-policy-found tickets; need enough to test the escalate-not-fabricate path")
for tid in nopol:
    check(labels[tid]["route"] == "ESCALATE", f"{tid} has no KB policy but does not escalate")

# ---------------------------------------------------------------- golden dataset
gd = load(DATA / "evaluation" / "golden_dataset.json")
recs = gd["records"]
check(len(recs) == gd["record_count"], "golden record_count mismatch")
seen = set()
for r in recs:
    tid = r["ticket_id"]
    check(tid in ids, f"golden record {tid} not in the ticket set")
    check(tid not in seen, f"golden record {tid} duplicated")
    seen.add(tid)
    check(r["expected_route"] == labels[tid]["route"],
          f"{tid} golden route disagrees with expected_routes.json")
    check(r["expected_route"] in ROUTES, f"{tid} bad golden route")
    lo, hi = r["expected_confidence_band"]
    check(0.0 <= lo < hi <= 1.0, f"{tid} bad confidence band")
    check(len(r["must_not_contain"]) >= 3, f"{tid} has too few prohibitions")
    check(bool(r["label_rationale"]), f"{tid} has no label rationale")

    for src in r["expected_kb_sources"]:
        check(src in KB_FILES, f"{tid} cites unknown KB file {src}")
    for pid in r["expected_policy_ids"]:
        check(pid in defined_ids, f"{tid} cites policy ID {pid} which is not defined in any KB file")
    # every cited policy ID must actually live in one of the cited source files
    for pid in r["expected_policy_ids"]:
        homes = [f for f in r["expected_kb_sources"] if pid in kb_text.get(f, "")]
        check(bool(homes), f"{tid} cites {pid} but none of its expected_kb_sources contain it")
    if r["no_policy_in_kb"]:
        check(not r["expected_policy_ids"], f"{tid} flagged no-policy but lists policy IDs")
        check(any("could not be verified" in c["claim"] for c in r["grounding_claims_required"]),
              f"{tid} no-policy record lacks the unverifiable-policy assertion")
    else:
        check(bool(r["grounding_claims_required"]), f"{tid} has no grounding claims")

# hard cases must be well represented in the golden set
gh = sum(1 for r in recs if r["difficulty"] == "hard")
check(gh == hard_n, f"golden set covers {gh} of {hard_n} hard tickets; it should cover all")

# ---------------------------------------------------------------- cross-cutting
# the KB must actually support every policy ID any label depends on
all_cited = {p for r in recs for p in r["expected_policy_ids"]}
all_cited |= {c["policy_id"] for r in recs for c in r["grounding_claims_required"] if c["policy_id"]}
orphans = sorted(all_cited - defined_ids)
check(not orphans, f"labels cite policy IDs with no KB definition: {orphans}")
unused = sorted(defined_ids - all_cited)
if unused:
    warns.append(f"{len(unused)} KB policy IDs are never exercised by a golden label: {unused}")

print(f"KB files                {len(kb_text)}")
print(f"policy IDs defined      {len(defined_ids)}")
print(f"tickets                 {len(tickets)}  (unique customers: {len(cust_ids)})")
print(f"route distribution      {dict(sorted(dist.items()))}")
print(f"hard cases              {hard_n}/150 ({hard_n / 1.5:.0f}%)")
print(f"no-policy-found cases   {len(nopol)}")
print(f"golden records          {len(recs)}  (all {gh} hard tickets covered)")
print(f"policy IDs exercised    {len(all_cited)}")

for w in warns:
    print(f"\nNOTE  {w}")

if fails:
    print(f"\nFAILED ({len(fails)}):")
    for f in fails:
        print(f"  - {f}")
    raise SystemExit(1)
print("\nAll integrity checks passed.")
