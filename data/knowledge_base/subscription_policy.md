# Account Servicing, Recurring Payments & Closure Policy

**Document ID:** KB-SUB-2026-01
**Owner:** Deposit Product Management & Deposit Operations
**Applies to:** Northgate Bank Customer Care (Tier 1 & Tier 2)
**Effective:** 2026-01-20
**Last reviewed:** 2026-06-30
**Classification:** Internal — Approved for agent-assist retrieval

> **Scope note.** Covers checking and savings package changes, monthly fee plans,
> recurring debit and preauthorized payment handling, stop payments, and account
> closure. Does **not** cover loan or credit card account closure, CD early-withdrawal
> penalty calculations, IRA distributions and transfers, safe deposit box termination,
> business treasury service agreements, or garnishment/levy releases. Outside these
> bounds, state that the policy could not be verified and escalate.

---

## 1. Product packages and plan changes (SUB)

### SUB-001 — Changing or downgrading a checking package
Current consumer packages:

| Package | Monthly fee | Waiver conditions | Notes |
| --- | --- | --- | --- |
| Everyday Checking | $12 | See `refund_policy.md` FEE-004 | Standard |
| Premier Checking | $25 | $25,000 combined balances | 2 out-of-network ATM reimbursements/cycle |
| Campus Checking | $0 | Ages 17–24, auto-converts at 25 | Converts to Everyday on 25th birthday |
| Basic Access Checking | $5 | None; no overdraft fees charged | No paper checks |

- Customers may change packages **once per 12 months** through
  **Settings → Accounts → Change account type**, or with agent assistance.
- Changes are effective the **first day of the next statement cycle**. The current
  cycle's fee is not prorated and is not refundable as an error.
- The **account number does not change** on a package change, and direct deposits,
  recurring debits and checks continue uninterrupted.
- A second package change inside 12 months requires Deposit Operations — escalate.
- **Campus Checking auto-conversion** at age 25 is disclosed 60 days in advance and
  cannot be extended. If a customer disputes the conversion fee, the fee is correctly
  assessed; a waiver is discretionary and belongs to Service Recovery — escalate.

### SUB-006 — Overdraft coverage election
- Customers may **opt out of overdraft coverage** for one-time debit card and ATM
  transactions at any time — self-service under **Settings → Overdraft options**.
  Opting out is effective immediately and cannot be refused.
- Opting **in** requires an affirmative election (Regulation E, §1005.17). An agent may
  record the election only in an authenticated channel.
- **Overdraft Protection transfer** from a linked savings is $0 per transfer and covers
  checks, ACH and debit alike; it requires a linked eligible account.
- Enrolling in coverage does **not** retroactively waive fees already assessed.

### SUB-007 — Statement delivery and paper statement fee
- e-Statements are $0. **Paper statements are $3.00 per cycle** on Everyday and Basic
  Access Checking, waived on Premier and Campus.
- Switching to e-Statements takes effect the next cycle; the current cycle's paper fee
  still applies.
- Customers who require paper statements as an **accessibility accommodation** are
  exempt from the fee. Record the request and process the exemption — do not require
  documentation, and do not route this to Service Recovery.
- Statement history available in digital banking: **7 years**. Older statements require a
  research request ($6 per statement) — escalate to Deposit Operations.

---

## 2. Recurring payments and stop payments

### SUB-003 — Closing an account with active recurring activity
Before closure, the customer must move or cancel:

- **Incoming:** payroll direct deposit, Social Security or other federal benefit,
  tax refunds, brokerage or transfer sweeps.
- **Outgoing:** preauthorized ACH debits (utilities, insurance, gym, streaming),
  card-on-file recurring charges, scheduled Bill Pay payments, external transfers.

The Bank **cannot cancel a customer's contract with a merchant**, and closing the
account does not terminate the merchant's authorization. Debits presented to a closed
account are returned, which may trigger **merchant late fees or returned-item fees at
the merchant's end** — the customer is responsible for those. Say this plainly and
kindly before closure.

Northgate provides a **Recurring Payments list** in digital banking
(**Accounts → Recurring activity**) showing the last 13 months of recurring debits and
credits, so customers can work through the list.

### SUB-004 — Stop payment on a preauthorized ACH debit
- Request must be received **at least 3 business days before** the scheduled debit date.
- A stop payment order on preauthorized transfers is valid for **6 months** and may be
  renewed. Stop payments on a specific **check** are valid for **6 months** as well.
- **Fee: $31 per stop payment order.** One stop payment fee per rolling 12 months is
  eligible for courtesy reversal under `refund_policy.md` FEE-001.
- Required at intake: exact merchant/originator name as it appears, expected amount (or
  amount range), expected date, and whether the customer wants **this occurrence only**
  or **all future debits**.
- If the debit has **already posted**, a stop payment cannot be applied. If the customer
  states they revoked authorization with the merchant and the merchant debited anyway,
  that is an **unauthorized transfer** — route under `refund_policy.md` DSP-001.
- If the exact amount and date are unknown and the debit is scheduled within 3 business
  days, tell the customer the order may not be effective in time and offer the
  alternative in SUB-005.

### SUB-005 — Revoking a merchant's authorization
1. The customer notifies the merchant of revocation — **in writing, and keeps a copy**.
2. The customer may also place a **debit block** on the originator through the Bank.
   Blocks are **best-effort**: merchants who change the originator ID, company name or
   amount can defeat the block.
3. If the merchant debits after documented revocation, the transfer is unauthorized —
   see `refund_policy.md` DSP-001, and note that the customer's written revocation is
   the key evidence.
4. For **card-on-file** recurring charges (not ACH), the customer should cancel with the
   merchant; a card reissue with a new number does **not** reliably stop recurring card
   charges, because networks forward updated card credentials to merchants
   automatically. Do not tell the customer a new card will stop the billing.

---

## 3. Account closure

### SUB-002 — Standard closure eligibility
An account may be closed on customer request when **all** of the following hold:

1. The **balance is zero**, or the customer has provided disbursement instructions.
2. There are **no pending or in-flight transactions** (holds, pending deposits,
   unposted checks, scheduled transfers within the next 3 business days).
3. The account is **not overdrawn** and has **no negative balance**.
4. There is **no open dispute, claim, or legal hold** on the account (see SUB-010).
5. The requester is an **owner**, authenticated in a secure channel.

**Disbursement of remaining funds:**

| Remaining balance | Handling |
| --- | --- |
| $0 | Close immediately |
| $0.01 – $999.99 | Transfer to a linked Northgate account, or mail a check to the address on file (7–10 business days) |
| $1,000 or more | **Escalate.** Requires verified disbursement method and secondary review |

Post-closure: the customer should keep records; the Bank retains statements and will
mail a final statement. Reopening a closed account is not possible — a new account must
be opened. Say so before closing, not after.

**Cooling-off guidance.** If the customer is closing because of a fee, a service
failure, or frustration expressed in the ticket, the drafted reply should acknowledge
the issue and offer the alternative path **once**, then honor the request. Do not
withhold or slow the closure, and do not require the customer to justify it.

### SUB-008 — Negative balance or charge-off status
Accounts with a **negative balance**, in **charge-off**, or referred to Recovery
**cannot be closed** on request. Escalate to the **Recovery team**, which will discuss
repayment options. Do not quote a payoff amount and do not state consequences such as
reporting to Early Warning Services — those statements require Recovery.

### SUB-009 — Dormant and escheatment-eligible accounts
- Accounts with no customer-initiated activity for **12 months** are flagged inactive;
  at **24 months** they are classified **dormant** and online access is restricted.
- Reactivation requires identity re-verification — **escalate to Deposit Operations** or
  direct to a branch.
- Accounts approaching **state escheatment** (unclaimed property, generally 3 years in
  most states, and the specific state schedule governs) receive a mailed notice.
  Do **not** quote a state-specific escheatment period; escalate for the exact date.

### SUB-010 — Closure requested while a dispute or claim is open
Hold the closure and **escalate**. Closing an account with an open Regulation E claim
can interrupt provisional credit and the final resolution credit. Explain that the
closure will be completed once the claim resolves, and that the customer is not
required to keep using the account in the meantime.

### SUB-011 — Bank-initiated closure inquiries
If a customer asks **why the Bank closed or restricted their account**, do not
speculate, do not read internal notes, and do not confirm the existence of a
suspicious-activity review. **Escalate to the Account Review team.** The only
permissible statement is that the request is being routed to the team that can respond.

---

## 4. Decision quick reference

| Customer situation | Route | Cite |
| --- | --- | --- |
| "Downgrade me from Premier to Everyday" | Auto-resolve | SUB-001 |
| "Change my package again" (changed 4 months ago) | Escalate — Deposit Operations | SUB-001 |
| "Close my checking, balance is $0" | Auto-resolve | SUB-002 |
| "Close my savings, there's $6,400 in it" | Escalate | SUB-002 |
| "Close it" — no account specified, two accounts on file | Ask for more information | SUB-002 |
| "Close my account, I'm overdrawn $212" | Escalate — Recovery | SUB-008 |
| "Close my account" with an open fraud claim | Escalate | SUB-010 |
| "Stop the $49.99 gym debit on the 3rd" | Auto-resolve — place stop payment | SUB-004 |
| "Stop a debit" — no merchant, amount or date | Ask for more information | SUB-004 |
| "The gym charged me again after I cancelled" | Route as unauthorized transfer | SUB-005, DSP-001 |
| "Send me paper statements, I'm blind and can't use the app" | Auto-resolve — fee exemption | SUB-007 |
| "Turn off overdraft coverage" | Auto-resolve | SUB-006 |
| "Why did you close my account?" | Escalate — Account Review | SUB-011 |
| "Waive my CD early withdrawal penalty" | **No policy in scope** — state as unverified and escalate | Scope note |

---

## 5. Related documents

- `refund_policy.md` — FEE-001 courtesy reversals, FEE-004 waiver criteria, DSP-001
- `troubleshooting_faq.md` — TRB-004 transfer timing, TRB-005 Bill Pay, TRB-011 direct deposit
- `account_access_faq.md` — ACC-009 joint owners and delegated access
- `abusive_content_policy.md` — CON-009 legal and regulator threats
