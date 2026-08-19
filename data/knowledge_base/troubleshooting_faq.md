# Payments, Cards & Digital Troubleshooting FAQ

**Document ID:** KB-TRB-2026-05
**Owner:** Payments Operations & Digital Support Engineering
**Applies to:** Northgate Bank Customer Care (Tier 1 & Tier 2)
**Effective:** 2026-05-11
**Last reviewed:** 2026-08-03
**Classification:** Internal — Approved for agent-assist retrieval

> **Scope note.** Covers debit card usage, mobile deposit, Zelle®, internal and external
> transfers, Bill Pay, mobile app faults, balance and hold questions, and statement/tax
> document access. Does **not** cover credit card servicing, loan payment posting,
> mortgage escrow, brokerage trading, business ACH origination files, merchant acquiring,
> or crypto exchange transfers. Outside these bounds, state that the policy could not be
> verified and escalate.

---

## 1. Published limits (shareable with customers)

| Activity | Standard limit | Premier limit |
| --- | --- | --- |
| ATM cash withdrawal | $500 / day | $1,000 / day |
| Debit card purchases (signature + PIN) | $2,500 / day | $5,000 / day |
| Zelle® send | $1,000 / day; $4,000 / 30 days | $2,500 / day; $10,000 / 30 days |
| Mobile check deposit | $5,000 / day; $10,000 / 30 days | $15,000 / day; $30,000 / 30 days |
| External transfer (ACH) out | $3,000 / day; $10,000 / 30 days | $10,000 / day; $25,000 / 30 days |
| Internal transfer between own accounts | No limit | No limit |
| Bill Pay single payment | $25,000 | $25,000 |

Limits reset on a **rolling** basis, not at midnight on the calendar day. Accounts open
**fewer than 30 days** carry reduced Zelle and mobile deposit limits ($500/day and
$2,000/day respectively) which lift automatically at day 31. Temporary limit increases
require Payments Operations — escalate; do not promise one.

---

## 2. Debit card (TRB-001, TRB-010)

### TRB-001 — Card declined
Work through in this order:

1. **Available vs. current balance.** Pending authorizations reduce available balance.
   See TRB-007.
2. **Daily limit reached** — see §1. Purchases and ATM withdrawals count separately.
3. **Merchant category or geography block.** Cards are enabled for international use
   only if travel notice or the "international purchases" toggle is on
   (**Card → Controls → International**).
4. **New card not activated.** Cards activate on first PIN transaction, in-app, or by
   phone. A newly issued card **deactivates the prior card immediately** on activation.
5. **Expired card.** Replacements mail automatically in the month before expiry; check
   the address on file.
6. **Card controls left on** — customers frequently lock a card in-app and forget
   (**Card → Lock card**). Check this early; it is the single most common cause.
7. **Fraud-prevention decline.** If steps 1–6 do not explain it, the decline may be a
   risk decision. Tell the customer the transaction was declined for security and that
   they can retry after confirming activity in the app. **Do not** disclose the rule,
   score, or threshold (`abusive_content_policy.md` CON-006). If the customer is stranded,
   travelling, or the decline blocks a medical or emergency payment, **escalate to
   Payments Operations at high priority** rather than iterating.

### TRB-010 — Lost, stolen or damaged card
- **Lost or stolen:** lock the card immediately in-app, then order a replacement. Locking
  is instant and reversible; reporting stolen permanently closes the card number.
- Standard replacement: **5–7 business days**, no fee. **Expedited: 2 business days,
  $30** (fee waivable once per 12 months under `refund_policy.md` FEE-001).
- **Damaged card** replacement is free and not expedited by default.
- A reissued card carries a **new number and CVV**; the expiry changes. Recurring
  **card-on-file** merchant charges often continue anyway via network account-updater
  services — do **not** tell the customer a new card stops a subscription
  (`subscription_policy.md` SUB-005).
- If the customer reports transactions they did not make, open a claim under
  `refund_policy.md` DSP-001 in the same interaction — do not make them contact us twice.
- **Card in a foreign country with no address access:** escalate to Payments Operations
  for emergency cash disbursement options.

---

## 3. Mobile deposit

### TRB-002 — Mobile check deposit: rejections, holds and funds availability

**Requirements**
- Endorse the back: signature plus **"For mobile deposit only at Northgate Bank."**
  Missing this restrictive endorsement is the most common rejection reason.
- Photograph on a dark, flat, non-reflective surface; all four corners visible; good even
  light; no flash glare.
- Amount typed must match the written amount exactly.
- Keep the paper check for **14 days** after the deposit posts, then destroy it.

**Funds availability**
- First **$225** available the **next business day**.
- Remainder generally available on the **second business day** after deposit.
- Deposits after the **7:00 PM PT cutoff**, or on weekends and federal holidays, are
  processed the next business day.
- **Extended holds of up to 7 business days** may apply to: accounts open fewer than 30
  days, deposits over $5,525 in one day, checks redeposited after being returned, an
  account with repeated overdrafts, or where the Bank has reasonable cause to doubt
  collectibility. A hold notice appears in the app and is mailed.

**Rejected deposits — common causes**

| Rejection | Explanation |
| --- | --- |
| Duplicate detected | The same check was already submitted; check the deposit history before resubmitting |
| Image quality | Retake per the guidance above |
| Endorsement missing | Add the restrictive endorsement and resubmit |
| Ineligible item | Foreign-currency checks, money orders over $1,000, third-party checks (payable to someone else and signed over), savings bonds, traveler's cheques, and checks dated more than 6 months prior |
| Payee mismatch | The payee name must match an account owner |
| Amount over limit | See §1 |

If a check was **accepted, then returned unpaid** (e.g. maker's insufficient funds), the
deposit is reversed and a **$12 Returned Deposit Item fee** applies. The customer must
pursue the check writer; the Bank cannot collect on their behalf. The fee is eligible for
courtesy reversal under FEE-001.

If a deposit shows **accepted in the app but no funds posted after 2 business days**,
escalate to Deposit Operations with the confirmation number.

---

## 4. Zelle® and transfers (TRB-003, TRB-004)

### TRB-003 — Zelle send and receive issues
- **Recipient not enrolled:** the payment stays **pending for up to 14 days** and then
  auto-cancels with funds returned. The customer may cancel a pending payment themselves
  (**Zelle → Activity → Cancel**).
- **Once the recipient is enrolled, the transfer is typically complete in minutes and
  cannot be cancelled.** Say this before the customer sends, when asked.
- **Wrong phone number or email:** if still pending, cancel. If delivered, the funds are
  gone from the Bank's control — a recall may be attempted; see `refund_policy.md`
  DSP-004.
- **Limit reached:** see §1; limits are rolling.
- **"Recipient already enrolled with another bank"** means their token is registered
  elsewhere; the payment will land at that institution, not at Northgate.
- **Scam or impostor claims** are never resolved in troubleshooting — escalate to Fraud
  Investigations, DSP-004.
- Zelle is unavailable to accounts open **fewer than 3 days** and to accounts with a
  restricted status.

### TRB-004 — Internal and external transfer timing

| Transfer type | Timing | Cutoff |
| --- | --- | --- |
| Between Northgate accounts | Immediate | None |
| External transfer out (standard ACH) | 1–3 business days | 5:00 PM PT |
| External transfer in (pull) | 3 business days; first $500 may be held | 5:00 PM PT |
| Scheduled/recurring transfer | Posts on the scheduled date if it is a business day; otherwise the next business day | — |
| Domestic wire out | Same business day | 2:00 PM PT |
| International wire out | 1–2 business days | 11:00 AM PT |

**Common issues:** a new external account requires **micro-deposit verification
(2 deposits, 1–2 business days)** before first use; transfers scheduled for a weekend
or federal holiday move to the next business day; a transfer is rejected if the external
account's ownership name does not match. Repeatedly failed external transfers may
restrict the external account link — escalate to Payments Operations.

### TRB-005 — Bill Pay
- **Electronic payees:** delivered in **2 business days**.
- **Check payees:** mailed and delivered in **5–7 business days**; funds debit when the
  payee **cashes** the check, not when it is mailed.
- A payment can be **cancelled or edited until 5:00 PM PT the business day before** the
  send date.
- **Payment not received:** if it has been **10 business days or more** past the send
  date, request a stop/reissue through Bill Pay Support — escalate with the payment
  confirmation number and payee details.
- Northgate's Bill Pay guarantee covers **late fees caused by a Bank processing error**.
  Do not promise reimbursement; escalate the claim with documentation of the payee's
  late fee.
- Payments to **tax authorities, court-ordered payments, and payments outside the US**
  are not supported through Bill Pay.

### TRB-011 — Direct deposit not received
1. Confirm the **expected pay date** with the customer. Deposits post as received from the
   originator, often between **12:01 AM and 6:00 AM PT** on the pay date.
2. Northgate does not hold or delay incoming direct deposits, and does not release them
   early. **Early Pay** (up to 2 days early) applies only when the employer transmits
   early; the timing is the employer's, not the Bank's.
3. If the deposit is **not received by end of the pay date**, the customer should confirm
   with their employer or payroll provider that it was sent and to which account.
4. If the employer confirms it was sent to the correct Northgate account and it has not
   posted by the **next business day**, escalate to Deposit Operations for an **ACH
   trace** with the amount, originator name and effective date.
5. Federal benefit payments (SSA, VA) follow a published payment schedule; direct
   customers to the agency for schedule questions.

---

## 5. Balances, holds and the app (TRB-006 – TRB-009)

### TRB-006 — App crashes, blank screen, or won't load
1. Confirm the app version (**Menu → About**); the supported baseline is in
   `account_access_faq.md` §3.
2. Force close and reopen. Then restart the device.
3. Switch between Wi-Fi and cellular — a captive-portal Wi-Fi (hotel, airport, café) is a
   frequent cause of a hanging splash screen.
4. Update the app; then update the device OS if below baseline.
5. Clear the app cache (Android) or reinstall (iOS). Warn that reinstalling requires
   re-enrolling biometrics (`account_access_faq.md` ACC-008) and re-trusting the device.
6. Corporate-managed devices and VPN or DNS-filtering profiles can block the app's API
   endpoints — try with the VPN off.
7. If the fault persists after these steps, or the customer reports it started after a
   specific release, escalate to Digital Support Engineering with the device model, OS
   version, app version, timestamp, and exact error text.

### TRB-012 — Suspected outage
Check **status.northgatebank.com** before deep troubleshooting. During a confirmed
incident: acknowledge the disruption, point to the status page, and note that no customer
action is needed. **Do not commit to a restoration time**, do not describe the cause, and
do not state how many customers are affected. If the customer incurred a fee or a missed
payment during a confirmed incident, note it on the ticket and escalate to Service
Recovery after restoration.

### TRB-007 — Balance looks wrong (available vs. current)
- **Current balance** = posted transactions only.
- **Available balance** = current balance − holds − pending debits + immediately available
  deposits. Available is the figure that governs whether a transaction clears.

**Typical authorization holds:**

| Merchant type | Typical hold |
| --- | --- |
| Fuel pump (pay at pump) | Up to $100, released in 1–3 business days |
| Hotel | Room total + up to 20% incidentals, released 3–5 business days after checkout |
| Car rental | Estimated total + $200, released 3–5 business days after return |
| Restaurant | Bill + ~20% tip estimate |
| Online grocery / curbside | Order estimate; adjusts at final pick |

Holds release automatically when the merchant settles. The Bank **cannot remove a
merchant's authorization hold** — only the merchant can, and their release still takes
1–3 business days to reflect. Setting that expectation clearly prevents a repeat contact.

### TRB-009 — "I was charged twice"
1. Determine whether **one entry is still pending**. A pending authorization plus a posted
   settlement for the same purchase is **one** transaction displayed twice — it resolves
   in **up to 3 business days**.
2. Check for a **pending authorization amount differing** from the posted amount (tips,
   fuel, adjusted orders). Also normal.
3. Only when **both entries have posted** and both have settled is it a true duplicate.
   Route under `refund_policy.md` DSP-002 (merchant duplicate) — advise the customer to
   also contact the merchant, which is usually faster than a claim.
4. **Recurring merchant billed twice in one month:** check for a plan change or billing
   date shift at the merchant before opening a claim.

### TRB-008 — Statements and tax documents
- e-Statements: available in digital banking within **2 business days** of cycle close;
  **7 years** of history.
- **1099-INT** (interest of $10 or more): posted and mailed by **January 31**.
- **1098** (mortgage interest): by **January 31**.
- **1099-R, 5498** (retirement): 1099-R by January 31; 5498 by May 31.
- **Corrected forms** are issued if information changes; the customer should wait for the
  corrected form rather than filing from the original.
- Documents are under **Statements & Documents → Tax documents**. Paper copies of tax
  forms are free; statement research copies older than 7 years are $6 each — escalate
  to Deposit Operations.
- Northgate cannot give tax advice. Direct tax treatment questions to a tax professional
  or IRS Publication 550 — this is not a refusal, it is a referral.

---

## 6. Decision quick reference

| Customer situation | Route | Cite |
| --- | --- | --- |
| "Card declined at the pump, I have money" | Auto-resolve — holds/limits/lock walkthrough | TRB-001, TRB-007 |
| "Card declined abroad, I'm stuck at a hotel" | Escalate — Payments Operations, high | TRB-001 |
| "Lost my card in a taxi" | Auto-resolve — lock + reissue | TRB-010 |
| "Mobile deposit keeps getting rejected" | Auto-resolve — endorsement/image guidance | TRB-002 |
| "Deposit accepted 4 days ago, no money" | Escalate — Deposit Operations | TRB-002 |
| "Zelle to my landlord is stuck pending" | Auto-resolve — recipient not enrolled | TRB-003 |
| "Zelle went to the wrong number" | Escalate — recall | TRB-003, DSP-004 |
| "Transfer says 3 days, why so slow" | Auto-resolve — ACH timing | TRB-004 |
| "Bill Pay check never arrived, sent 14 days ago" | Escalate — Bill Pay Support | TRB-005 |
| "Paycheck isn't in yet, pay date is today" | Auto-resolve — employer timing explanation | TRB-011 |
| "Employer confirms it was sent 3 days ago" | Escalate — ACH trace | TRB-011 |
| "App won't open" — no device details | Ask for more information | TRB-006 |
| "Charged twice" — one entry pending | Auto-resolve — explain hold | TRB-009, TRB-007 |
| "Charged twice" — both posted | Route as merchant dispute | TRB-009, DSP-002 |
| "Where's my 1099-INT" (February) | Auto-resolve — location + timing | TRB-008 |
| "How do I report the interest on my taxes?" | Referral to tax professional (not a refusal) | TRB-008 |
| "Transfer to my crypto exchange failed" | **No policy in scope** — state as unverified and escalate | Scope note |

---

## 7. Related documents

- `refund_policy.md` — DSP-001/DSP-002 claims, FEE-001 courtesy reversals
- `account_access_faq.md` — sign-in, OTP, device trust, supported versions
- `subscription_policy.md` — SUB-004 stop payments, SUB-005 recurring revocation
- `abusive_content_policy.md` — CON-006 internal controls, CON-011 tone handling
