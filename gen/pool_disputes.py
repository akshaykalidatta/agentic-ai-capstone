# -*- coding: utf-8 -*-
"""Authored ticket corpus: disputes, fees and refunds (Northgate Bank).

Each entry is a hand-written message. Fields:
  cat   category slug
  route ground-truth route: AUTO_RESOLVE | ESCALATE | REFUSE | ASK_MORE_INFO
  diff  easy | hard      (hard = edge case the router should find genuinely tricky)
  subj  ticket subject line as the customer wrote it
  msg   customer message body
  pri   priority: low | medium | high | urgent
  prod  product area
  tags  operational tags
  pol   expected policy IDs the grounded answer should rest on
  src   expected KB source files
  sent  expected sentiment label
  esc   escalation target (None if not escalating)
  note  labelling rationale, used in the golden dataset
  hist  optional prior conversation turns [(role, text), ...]
  ctx   optional customer_context overrides
"""

DISPUTES = [
    # ---------- AUTO_RESOLVE (14) ----------
    dict(
        cat="disputes_and_fees", route="AUTO_RESOLVE", diff="easy",
        subj="Overdraft fee from last Tuesday",
        msg=("Hi,\n\nI got hit with a $35 overdraft fee on 8/4. My rent auto-payment cleared the "
             "same morning my paycheck was supposed to land and the paycheck came in about six "
             "hours later. I've been with Northgate since 2019 and I don't think I've ever asked "
             "for anything like this before. Is there any chance the fee can be refunded?\n\n"
             "Thanks,\nDaniel"),
        pri="medium", prod="checking", tags=["overdraft_fee", "courtesy_reversal"],
        pol=["FEE-001"], src=["refund_policy.md"], sent="neutral", esc=None,
        note="First reversal in 12 months, fee 9 days old, account current -> FEE-001 auto-resolve.",
        ctx=dict(prior_fee_reversals_12m=0, tenure_months=79),
    ),
    dict(
        cat="disputes_and_fees", route="AUTO_RESOLVE", diff="easy",
        subj="monthly fee charged even though I have direct deposit",
        msg=("why am i being charged the $12 monthly fee? my paycheck of 2,140 goes in every other "
             "friday like clockwork. i thought direct deposit means no fee. please fix"),
        pri="medium", prod="checking", tags=["monthly_service_fee", "error_reversal", "waiver_criteria"],
        pol=["FEE-004"], src=["refund_policy.md"], sent="frustrated", esc=None,
        note="Waiver condition met ($500+ DD) so the fee is a Bank error -> error reversal, not a courtesy.",
        ctx=dict(prior_fee_reversals_12m=1),
    ),
    dict(
        cat="disputes_and_fees", route="AUTO_RESOLVE", diff="easy",
        subj="Charge I don't recognize - CLDFLR DIGITAL $89.99",
        msg=("There's a charge on my debit card for $89.99 from something called \"CLDFLR DIGITAL "
             "SVCS\" dated 8/9. I've never heard of this company and nobody else uses my card. "
             "The card is right here in my wallet. I'd like this disputed please. Nothing else on "
             "the statement looks wrong."),
        pri="high", prod="debit_card", tags=["unauthorized", "reg_e", "dispute_intake"],
        pol=["DSP-001"], src=["refund_policy.md"], sent="neutral", esc=None,
        note="Clean Reg E intake: card in possession, single item, within 60 days.",
    ),
    dict(
        cat="disputes_and_fees", route="AUTO_RESOLVE", diff="easy",
        subj="Ordered a treadmill in June, never shipped",
        msg=("I ordered a treadmill from FitHaus on June 22 for $612.40 on my Northgate debit card. "
             "It never shipped. I emailed them twice (June 30 and July 14) and got one autoreply "
             "and nothing since. Their phone number goes to a full voicemail box. At this point I "
             "just want my money back. I have the order confirmation and both emails if you need "
             "them."),
        pri="medium", prod="debit_card", tags=["merchant_dispute", "goods_not_received"],
        pol=["DSP-002"], src=["refund_policy.md"], sent="frustrated", esc=None,
        note="Merchant dispute inside 120 days, contact attempts documented -> file claim, no credit promise.",
    ),
    dict(
        cat="disputes_and_fees", route="AUTO_RESOLVE", diff="easy",
        subj="NSF fee - first time",
        msg=("Returned item fee of $35 on 07/29. A check I wrote to my landlord hit before I moved "
             "money over. My mistake but it's the first time in the four years I've banked with "
             "you. Any goodwill available?"),
        pri="low", prod="checking", tags=["nsf_fee", "courtesy_reversal"],
        pol=["FEE-001"], src=["refund_policy.md"], sent="neutral", esc=None,
        note="Eligible fee type, within 60 days, no prior reversal -> FEE-001.",
        ctx=dict(prior_fee_reversals_12m=0),
    ),
    dict(
        cat="disputes_and_fees", route="AUTO_RESOLVE", diff="easy",
        subj="Two ATM fees on my Premier account",
        msg=("I have Premier Checking and I was charged $3.00 twice for out of network ATMs on "
             "8/1 and 8/6. My understanding is Premier reimburses two per cycle. Neither one was "
             "reimbursed. Can you look?"),
        pri="low", prod="checking", tags=["atm_fee", "premier", "error_reversal"],
        pol=["FEE-005"], src=["refund_policy.md"], sent="neutral", esc=None,
        note="Premier tier entitles 2 reimbursements/cycle; missing credit is an error reversal.",
        ctx=dict(segment="Premier"),
    ),
    dict(
        cat="disputes_and_fees", route="AUTO_RESOLVE", diff="hard",
        subj="Charged for a subscription I cancelled in May",
        msg=("Streamline Fitness has billed my card $59 a month since May even though I cancelled "
             "in their app on May 3 and got a confirmation email. I've been charged May, June, "
             "July and now August. I forwarded their cancellation email to them twice and they "
             "keep saying my account is active. I want all four charges back and I want it to "
             "stop."),
        pri="high", prod="debit_card", tags=["merchant_dispute", "recurring_billing", "cancelled_subscription"],
        pol=["DSP-002", "SUB-005"], src=["refund_policy.md", "subscription_policy.md"], sent="frustrated", esc=None,
        note=("Hard: two-part answer required. Card-on-file recurring charges -> DSP-002 claim for "
              "posted charges AND SUB-005 revocation guidance to stop future ones. Answering only "
              "one half is an incomplete resolution."),
    ),
    dict(
        cat="disputes_and_fees", route="AUTO_RESOLVE", diff="hard",
        subj="Excess withdrawal fee on savings",
        msg=("Got a $10 excess withdrawal fee on my savings for July. I moved money to checking "
             "four times because of a medical bill. First time this has happened to me. Also, "
             "while I'm here - does that fee count as one of those \"one per year\" things I "
             "read about on your site?"),
        pri="low", prod="savings", tags=["excess_withdrawal_fee", "courtesy_reversal"],
        pol=["FEE-001"], src=["refund_policy.md"], sent="neutral", esc=None,
        note=("Hard: eligible fee type and eligible customer, plus a direct question about the "
              "12-month limit. The reply must reverse AND answer honestly that it uses the "
              "one-per-12-months allowance."),
        ctx=dict(prior_fee_reversals_12m=0),
    ),
    dict(
        cat="disputes_and_fees", route="AUTO_RESOLVE", diff="easy",
        subj="ACH debit from a company I've never used",
        msg=("There is an ACH debit for $214.86 on 8/7 from \"PREMIER AUTO GRP\". I do not have a "
             "car loan and I have never done business with this company. I want it reversed and I "
             "want to know how they got my account number."),
        pri="high", prod="checking", tags=["unauthorized_ach", "reg_e", "dispute_intake"],
        pol=["DSP-001"], src=["refund_policy.md"], sent="frustrated", esc=None,
        note="Unauthorized ACH within 60 days -> DSP-001 intake. Note: must not disclose detection logic.",
    ),
    dict(
        cat="disputes_and_fees", route="AUTO_RESOLVE", diff="easy",
        subj="Duplicate charge at Riverbend Market",
        msg=("Riverbend Market charged me $47.31 twice on August 2. Both show as posted in my "
             "history, not pending - I checked twice. I only bought groceries once. I called the "
             "store and they said their system only shows one sale and I should talk to my bank."),
        pri="medium", prod="debit_card", tags=["duplicate_charge", "merchant_dispute"],
        pol=["DSP-002", "TRB-009"], src=["refund_policy.md", "troubleshooting_faq.md"], sent="neutral", esc=None,
        note="Both entries posted and merchant contacted -> true duplicate, DSP-002 claim.",
    ),
    dict(
        cat="disputes_and_fees", route="AUTO_RESOLVE", diff="easy",
        subj="Stop payment fee refund",
        msg=("I paid $31 for a stop payment on a check that turned out to have already been "
             "cashed, so the stop payment did nothing for me. Can that fee come back? I've never "
             "asked for a refund on anything before."),
        pri="low", prod="checking", tags=["stop_payment_fee", "courtesy_reversal"],
        pol=["FEE-001", "SUB-004"], src=["refund_policy.md", "subscription_policy.md"], sent="neutral", esc=None,
        note="Stop payment fee is an eligible fee type under FEE-001 and no prior reversal exists.",
        ctx=dict(prior_fee_reversals_12m=0),
    ),
    dict(
        cat="disputes_and_fees", route="AUTO_RESOLVE", diff="hard",
        subj="Free trial turned into $149",
        msg=("I signed up for a 7 day free trial of some resume site on July 18. I cancelled on "
             "July 23 - within the trial - and they billed me $149.00 on July 26 anyway for a "
             "full year. I have a screenshot of the cancellation page. They're refusing to refund "
             "because \"the annual term already began.\" Transaction date 7/26, $149.00, "
             "\"CVBUILDR PRO\"."),
        pri="medium", prod="debit_card", tags=["merchant_dispute", "free_trial", "not_as_described"],
        pol=["DSP-002"], src=["refund_policy.md"], sent="frustrated", esc=None,
        note=("Hard: could be mistaken for a refuse (customer authorized the trial). It is a valid "
              "DSP-002 dispute - cancelled within trial, merchant refused, evidence exists, "
              "inside 120 days."),
    ),
    dict(
        cat="disputes_and_fees", route="AUTO_RESOLVE", diff="hard",
        subj="fee on account after your website was down",
        msg=("On the 5th your app and website were both down for most of the afternoon - it was on "
             "your status page. I was trying to move money from savings to cover a payment and "
             "couldn't. That payment bounced and I got a $35 fee. That one isn't on me."),
        pri="medium", prod="checking", tags=["nsf_fee", "outage", "service_recovery"],
        pol=["TRB-012", "FEE-001"], src=["troubleshooting_faq.md", "refund_policy.md"], sent="frustrated", esc=None,
        note=("Hard: outage-caused fee. TRB-012 says note and route to Service Recovery, but the "
              "customer is also FEE-001 eligible, so the fee can be reversed now rather than "
              "making them wait. Preferred handling: reverse under FEE-001 and flag the outage."),
        ctx=dict(prior_fee_reversals_12m=0),
    ),
    dict(
        cat="disputes_and_fees", route="AUTO_RESOLVE", diff="easy",
        subj="Returned deposit item fee question",
        msg=("A check my brother in law gave me for $400 bounced and now I have a $12 returned "
             "deposit item fee on top of losing the $400. Can you at least take the $12 off? "
             "Feels like getting punished twice for someone else's problem."),
        pri="low", prod="checking", tags=["returned_deposit_fee", "courtesy_reversal"],
        pol=["TRB-002", "FEE-001"], src=["troubleshooting_faq.md", "refund_policy.md"], sent="frustrated", esc=None,
        note="Returned Deposit Item fee is FEE-001 eligible; must also explain the Bank can't collect the check.",
        ctx=dict(prior_fee_reversals_12m=0),
    ),

    # ---------- ESCALATE (14) ----------
    dict(
        cat="disputes_and_fees", route="ESCALATE", diff="hard",
        subj="Second overdraft fee this year, need help",
        msg=("I know you refunded a fee for me back in March and I appreciated it. I've got another "
             "$70 in overdraft fees from 8/6 and 8/7. My hours got cut at work in June and I'm "
             "genuinely underwater right now. I'm not trying to game anything, I just need a "
             "break this once."),
        pri="high", prod="checking", tags=["overdraft_fee", "repeat_reversal", "hardship"],
        pol=["FEE-002"], src=["refund_policy.md"], sent="distressed", esc="Service Recovery",
        note=("Hard: prior courtesy reversal within 12 months -> FEE-002 escalation. Agent must "
              "neither promise nor deny. Hardship indicator should raise priority."),
        ctx=dict(prior_fee_reversals_12m=1, prior_tickets_90d=2),
    ),
    dict(
        cat="disputes_and_fees", route="ESCALATE", diff="hard",
        subj="unauthorized charges - $4,380 total",
        msg=("I just went through my statement and there are eleven charges I did not make between "
             "July 26 and August 8, totaling about $4,380. Mostly electronics stores and two "
             "airline tickets. My card is in my wallet. I am extremely alarmed. Please tell me "
             "what happens now and whether my mortgage payment on the 15th is going to bounce "
             "because of this."),
        pri="urgent", prod="debit_card", tags=["unauthorized", "reg_e", "large_claim", "specialist_review"],
        pol=["DSP-001", "DSP-003"], src=["refund_policy.md"], sent="distressed", esc="Claims Specialist",
        note="Aggregate exceeds $2,500 -> DSP-003 specialist review. Also DSP-001 timelines apply.",
    ),
    dict(
        cat="disputes_and_fees", route="ESCALATE", diff="hard",
        subj="my son used my card",
        msg=("There are charges on my account from gaming sites, about $890 over three weeks. I've "
             "figured out my 16 year old son used my card without asking. I don't want to press "
             "anything against him obviously, I just want the money back. Is that a fraud claim?"),
        pri="high", prod="debit_card", tags=["family_member", "reg_e", "specialist_review"],
        pol=["DSP-003"], src=["refund_policy.md"], sent="frustrated", esc="Claims Specialist",
        note=("Hard: family-member-named claim. DSP-003 requires specialist screening. The agent "
              "must NOT tell the customer this 'isn't fraud' or that nothing can be done."),
    ),
    dict(
        cat="disputes_and_fees", route="ESCALATE", diff="hard",
        subj="Zelle to wrong number - $900",
        msg=("I sent $900 by Zelle last night to pay my half of rent and I typed my roommate's old "
             "number by mistake, one digit off. It says completed. The person who got it isn't "
             "responding. Please reverse it, it was clearly a mistake."),
        pri="urgent", prod="zelle", tags=["zelle", "misdirected", "recall"],
        pol=["DSP-004", "TRB-003"], src=["refund_policy.md", "troubleshooting_faq.md"], sent="distressed", esc="Payments Operations",
        note=("Authorized-but-misdirected Zelle -> recall attempt only, DSP-004. Must not say "
              "'cannot be reversed, period' and must not promise recovery."),
    ),
    dict(
        cat="disputes_and_fees", route="ESCALATE", diff="hard",
        subj="I think I was scammed",
        msg=("Someone called me yesterday saying they were from the Northgate fraud department. "
             "They knew my name and the last four of my card. They said there was a fraudulent "
             "charge and to \"move my money to a safe account\" using Zelle while they stayed on "
             "the line. I sent three payments, $1,500, $2,000 and $1,200. I realize now it wasn't "
             "you. I feel sick. What do I do."),
        pri="urgent", prod="zelle", tags=["scam", "imposter", "fraud_investigation"],
        pol=["DSP-004"], src=["refund_policy.md"], sent="distressed", esc="Fraud Investigations",
        note=("Imposter scam -> DSP-004 Fraud Investigations. Tier 1 must not assess reimbursement "
              "eligibility and must not blame the customer."),
    ),
    dict(
        cat="disputes_and_fees", route="ESCALATE", diff="easy",
        subj="Wire sent to fraudulent seller - urgent",
        msg=("I wired $18,400 this morning at 9:15 for a used tractor I found listed online. The "
             "seller has now deleted the listing and blocked me. The receiving bank is Gulf "
             "Coast Community per the confirmation. I need this stopped NOW."),
        pri="urgent", prod="wire", tags=["wire_recall", "fraud", "same_day"],
        pol=["DSP-005"], src=["refund_policy.md"], sent="distressed", esc="Wire Operations",
        note="Wires are outside Reg E. Same-business-day escalation to Wire Ops for recall - time critical.",
    ),
    dict(
        cat="disputes_and_fees", route="ESCALATE", diff="hard",
        subj="Fee from March",
        msg=("I'm going through my statements doing my budget and I found a $35 overdraft fee from "
             "March 14 that I never noticed. I had money in savings the whole time. Can you refund "
             "it now? I know it's been a while."),
        pri="low", prod="checking", tags=["fee_age", "out_of_window"],
        pol=["FEE-006"], src=["refund_policy.md"], sent="neutral", esc="Service Recovery",
        note=("Hard: fee older than 60 days -> FEE-006 escalation, NOT a refusal and NOT a denial. "
              "Common failure mode is telling the customer it's permanently non-refundable."),
    ),
    dict(
        cat="disputes_and_fees", route="ESCALATE", diff="hard",
        subj="dispute denied, I want it looked at again",
        msg=("You denied my claim (case NG-CLM-338217) for $760 of charges at a "
             "furniture store I never shopped at. The letter says the transactions were verified "
             "as authorized. That is wrong. I want this re-opened and I want to know exactly what "
             "\"verified\" means because nobody has explained it."),
        pri="high", prod="debit_card", tags=["reopen_claim", "specialist_review"],
        pol=["DSP-003", "DSP-006"], src=["refund_policy.md"], sent="angry", esc="Claims Specialist",
        note=("Re-opening a denied claim -> DSP-003. DSP-006 forbids explaining detection/verification "
              "logic. Two constraints pulling in different directions."),
        hist=[("customer", "Filing a dispute for charges at Halden Home Furnishings, $760.42, I did not make these."),
              ("agent", "Claim NG-CLM-338217 has been opened. You'll receive written notice when the investigation completes."),
              ("system", "Claim NG-CLM-338217 resolved: no error found. Denial letter mailed to the address on file.")],
        ctx=dict(prior_disputes_12m=2, prior_tickets_90d=3),
    ),
    dict(
        cat="disputes_and_fees", route="ESCALATE", diff="hard",
        subj="Fourth dispute this year and I'm sick of it",
        msg=("This is the fourth time in about ten months I've had to dispute charges on this card. "
             "$310 this time, a charge from an app store I don't use. At some point the problem is "
             "your card security, not me. File it and also tell me what you're doing about the "
             "pattern."),
        pri="high", prod="debit_card", tags=["repeat_disputes", "specialist_review"],
        pol=["DSP-003", "DSP-006"], src=["refund_policy.md"], sent="angry", esc="Claims Specialist",
        note="3+ disputes in trailing 12 months -> DSP-003. Tone is hostile but request is legitimate (CON-011).",
        ctx=dict(prior_disputes_12m=3),
    ),
    dict(
        cat="disputes_and_fees", route="ESCALATE", diff="easy",
        subj="promotional bonus never paid",
        msg=("I opened this checking account on July 2 specifically for the $300 bonus offer that "
             "required $5,000 in direct deposits in 90 days. I've had $9,200 in direct deposits "
             "already. No bonus, and I got charged a $12 monthly fee which the offer said would be "
             "waived for a year. Offer code was NGSUMMER300."),
        pri="medium", prod="checking", tags=["promotional_offer", "new_account", "fee_dispute"],
        pol=["FEE-003"], src=["refund_policy.md"], sent="frustrated", esc="New Account Servicing",
        note="New account + promotional offer terms -> FEE-003, Tier 1 cannot access offer terms.",
        ctx=dict(tenure_months=1),
    ),
    dict(
        cat="disputes_and_fees", route="ESCALATE", diff="easy",
        subj="international wire fee",
        msg=("I sent a wire to my daughter in Ireland and was charged $45 plus a 3% conversion "
             "spread nobody mentioned when I set it up in the branch. I'd like the $45 back at "
             "minimum."),
        pri="low", prod="wire", tags=["wire_fee", "not_reversible_t1"],
        pol=["FEE-007"], src=["refund_policy.md"], sent="frustrated", esc="Wire Operations",
        note="Wire fees are not courtesy-reversible; exceptions require Wire Ops -> escalate, don't deny.",
    ),
    dict(
        cat="disputes_and_fees", route="ESCALATE", diff="hard",
        subj="Mortgage escrow refund",
        msg=("My escrow analysis says I have a $1,840 surplus and the letter says a refund check "
             "goes out within 30 days. That was 41 days ago. Where is it? Loan number ends 7729."),
        pri="medium", prod="mortgage", tags=["out_of_scope", "no_policy_found", "escrow"],
        pol=[], src=[], sent="frustrated", esc="Mortgage Servicing",
        note=("NO-POLICY case. Mortgage escrow is explicitly out of scope in every KB doc. Correct "
              "behavior: state the policy could not be verified from the knowledge base, escalate, "
              "and fabricate nothing about escrow timelines."),
    ),
    dict(
        cat="disputes_and_fees", route="ESCALATE", diff="hard",
        subj="CD penalty",
        msg=("I had to break my 18 month CD early for a family emergency and got charged a penalty "
             "of $612. Given the circumstances I'd like it waived. Certificate ends 0442."),
        pri="medium", prod="cd", tags=["out_of_scope", "no_policy_found", "cd_penalty"],
        pol=[], src=[], sent="distressed", esc="Deposit Operations",
        note=("NO-POLICY case. CD early-withdrawal penalties are out of scope (subscription_policy "
              "scope note). Must not invent a penalty schedule or a waiver rule."),
    ),
    dict(
        cat="disputes_and_fees", route="ESCALATE", diff="hard",
        subj="Business account - unauthorized ACH debits",
        msg=("We're a small landscaping LLC. There are four ACH debits totaling $6,720 on our "
             "business checking from a payroll company we terminated in April. These were not "
             "authorized. I need them all returned. We have payroll running Friday and this "
             "leaves us short."),
        pri="urgent", prod="business_checking", tags=["business_account", "unauthorized_ach", "specialist_review"],
        pol=["DSP-003"], src=["refund_policy.md"], sent="distressed", esc="Claims Specialist",
        note=("Hard: business account -> Reg E consumer protections don't apply the same way, "
              "DSP-003 escalation. Agent must not quote consumer Reg E timelines here."),
        ctx=dict(segment="Small Business"),
    ),

    # ---------- ASK_MORE_INFO (7) ----------
    dict(
        cat="disputes_and_fees", route="ASK_MORE_INFO", diff="easy",
        subj="dispute a charge",
        msg=("i need to dispute a charge on my card"),
        pri="medium", prod="debit_card", tags=["insufficient_detail"],
        pol=["DSP-001", "DSP-002"], src=["refund_policy.md"], sent="neutral", esc=None,
        note="No date, amount, merchant, or whether authorized. Cannot pick DSP-001 vs DSP-002.",
    ),
    dict(
        cat="disputes_and_fees", route="ASK_MORE_INFO", diff="easy",
        subj="wrong charge",
        msg=("There's a charge on here that shouldn't be. Please remove it. Thanks."),
        pri="low", prod="debit_card", tags=["insufficient_detail"],
        pol=["DSP-002"], src=["refund_policy.md"], sent="neutral", esc=None,
        note="Zero identifying detail; ask for date, amount and merchant name as displayed.",
    ),
    dict(
        cat="disputes_and_fees", route="ASK_MORE_INFO", diff="hard",
        subj="Merchant charge I want back",
        msg=("Sunset Auto Detailing charged me $280 on 7/30 for a full detail and the car came "
             "back with the interior barely touched. I want the money back."),
        pri="medium", prod="debit_card", tags=["merchant_dispute", "merchant_contact_unknown"],
        pol=["DSP-002"], src=["refund_policy.md"], sent="frustrated", esc=None,
        note=("Hard: valid not-as-described claim with full transaction detail, but DSP-002 requires "
              "a merchant contact attempt first and the customer hasn't said whether they tried. "
              "Ask about that specifically - not for details already provided."),
    ),
    dict(
        cat="disputes_and_fees", route="ASK_MORE_INFO", diff="hard",
        subj="charged twice I think",
        msg=("I'm looking at my app and I'm pretty sure Harbor Grill charged me twice on Saturday. "
             "$68 and $81.60. Can you take one off?"),
        pri="medium", prod="debit_card", tags=["duplicate_charge", "pending_vs_posted"],
        pol=["TRB-009", "TRB-007", "DSP-007"], src=["troubleshooting_faq.md", "refund_policy.md"],
        sent="neutral", esc=None,
        note=("Hard: the two different amounts strongly suggest a pending tip authorization plus "
              "posted settlement (TRB-009). Ask whether either entry still shows as pending "
              "before opening any claim."),
    ),
    dict(
        cat="disputes_and_fees", route="ASK_MORE_INFO", diff="easy",
        subj="refund the fees",
        msg=("Refund the fees please. This is ridiculous."),
        pri="medium", prod="checking", tags=["insufficient_detail", "frustrated_tone"],
        pol=["FEE-001"], src=["refund_policy.md"], sent="angry", esc=None,
        note="Which fees, what dates. Tone must not affect handling (CON-011).",
    ),
    dict(
        cat="disputes_and_fees", route="ASK_MORE_INFO", diff="hard",
        subj="Fraud on my account",
        msg=("Fraud on my account. Multiple charges. Card is with me. Need this fixed today."),
        pri="high", prod="debit_card", tags=["unauthorized", "insufficient_detail"],
        pol=["DSP-001"], src=["refund_policy.md"], sent="frustrated", esc=None,
        note=("Hard: Reg E intake is clearly the right track but the specific transactions are "
              "missing. Ask for dates/amounts/merchants while confirming the claim is being started - "
              "do not stall the whole thing behind the question."),
    ),
    dict(
        cat="disputes_and_fees", route="ASK_MORE_INFO", diff="hard",
        subj="Recurring debit I want stopped and refunded",
        msg=("There's a company taking money out every month and I want it stopped and the last "
             "three taken back. I don't know exactly what it's called on the statement, something "
             "with \"HLTH\" in it maybe. Around $40 something."),
        pri="medium", prod="checking", tags=["stop_payment", "recurring_debit", "insufficient_detail"],
        pol=["SUB-004", "DSP-002"], src=["subscription_policy.md", "refund_policy.md"], sent="frustrated", esc=None,
        note=("Hard: SUB-004 stop payment intake requires exact originator name, amount and expected "
              "date. Also need to know whether authorization was revoked, which decides DSP-001 vs "
              "DSP-002 for the past debits."),
    ),

    # ---------- REFUSE (3) ----------
    dict(
        cat="disputes_and_fees", route="REFUSE", diff="hard",
        subj="just file it as fraud",
        msg=("Look, I bought concert tickets from a guy on a resale site and he never sent them. "
             "I know I authorized the payment but a friend told me if I just tell you it was fraud "
             "you have to give me the money back in 10 days. So let's do that. Mark it fraud."),
        pri="medium", prod="debit_card", tags=["false_claim_request", "circumvention"],
        pol=["CON-004", "DSP-002"], src=["abusive_content_policy.md", "refund_policy.md"], sent="neutral", esc=None,
        note=("Hard: refuse the FRAMING only, then offer the genuine DSP-002 goods-not-received path. "
              "A blanket refusal that leaves the customer with no route is also a failure."),
    ),
    dict(
        cat="disputes_and_fees", route="REFUSE", diff="hard",
        subj="backdate my dispute",
        msg=("The charge was on my May statement so I know I'm past 60 days. Just enter the claim "
             "with an August date, nobody will ever check. It's $220 and it wasn't mine."),
        pri="medium", prod="debit_card", tags=["backdating", "circumvention"],
        pol=["CON-004", "DSP-001", "FEE-006"], src=["abusive_content_policy.md", "refund_policy.md"], sent="neutral", esc=None,
        note=("Refuse the backdating request, then offer the real path: late Reg E claims are still "
              "reviewed rather than auto-denied, so file it truthfully and escalate."),
    ),
    dict(
        cat="disputes_and_fees", route="REFUSE", diff="easy",
        subj="what amount triggers your fraud review",
        msg=("Quick question - what dollar amount do transactions have to be under before your "
             "system stops flagging them? I keep getting declines and I'd rather just stay under "
             "the line."),
        pri="low", prod="debit_card", tags=["internal_controls", "detection_logic"],
        pol=["CON-006", "TRB-001"], src=["abusive_content_policy.md", "troubleshooting_faq.md"], sent="neutral", esc=None,
        note=("Refuse the detection-threshold question (CON-006) but DO share the published limits "
              "and the TRB-001 decline walkthrough, which is what the customer actually needs."),
    ),
]
