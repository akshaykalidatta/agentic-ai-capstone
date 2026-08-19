# -*- coding: utf-8 -*-
"""Authored ticket corpus: payments, cards, deposits, app troubleshooting."""

TROUBLESHOOTING = [
    # ---------- AUTO_RESOLVE (15) ----------
    dict(
        cat="payments_troubleshooting", route="AUTO_RESOLVE", diff="easy",
        subj="card declined at gas station but I have money",
        msg=("My card got declined at the pump this morning. My app says I have $840 available. It "
             "worked at the grocery store an hour earlier. Embarrassing and confusing."),
        pri="medium", prod="debit_card", tags=["decline", "fuel_hold", "card_lock"],
        pol=["TRB-001", "TRB-007"], src=["troubleshooting_faq.md"], sent="frustrated", esc=None,
        note="TRB-001 walkthrough with fuel pre-auth context. Check the in-app card lock early - most common cause.",
    ),
    dict(
        cat="payments_troubleshooting", route="AUTO_RESOLVE", diff="easy",
        subj="mobile deposit keeps getting rejected",
        msg=("Third time trying to deposit a check for $1,240 and it keeps failing. It says image "
             "quality. I'm taking the photo on my kitchen counter which is white marble, in good "
             "light. I signed the back."),
        pri="medium", prod="mobile_deposit", tags=["mobile_deposit", "image_quality", "endorsement"],
        pol=["TRB-002"], src=["troubleshooting_faq.md"], sent="frustrated", esc=None,
        note=("Two likely causes: glare from a reflective white marble surface, and a missing "
              "restrictive endorsement ('For mobile deposit only at Northgate Bank') - a plain "
              "signature is not enough. Both are in TRB-002."),
        hist=[("system", "Mobile deposit MD-77201883 rejected: image quality - front image unreadable."),
              ("system", "Mobile deposit MD-77203114 rejected: image quality - front image unreadable.")],
        hspan=(14, 26),
    ),
    dict(
        cat="payments_troubleshooting", route="AUTO_RESOLVE", diff="easy",
        subj="Zelle stuck on pending for 2 days",
        msg=("I sent $450 to my landlord on Monday via Zelle and it still says pending. He says he "
             "never got anything. Did it go through or not? Rent is late now."),
        pri="high", prod="zelle", tags=["zelle", "pending", "not_enrolled"],
        pol=["TRB-003"], src=["troubleshooting_faq.md"], sent="frustrated", esc=None,
        note="Pending = recipient not enrolled. 14-day window then auto-cancel; customer can cancel now.",
    ),
    dict(
        cat="payments_troubleshooting", route="AUTO_RESOLVE", diff="easy",
        subj="why does a transfer take 3 days",
        msg=("I moved $500 from Northgate to my credit union on Friday afternoon and it still isn't "
             "there Monday. Every other bank I've used does this instantly. What's the holdup?"),
        pri="medium", prod="transfers", tags=["ach_timing", "external_transfer"],
        pol=["TRB-004"], src=["troubleshooting_faq.md"], sent="frustrated", esc=None,
        note="Standard ACH 1-3 business days; Friday after 5PM PT cutoff plus a weekend explains it exactly.",
    ),
    dict(
        cat="payments_troubleshooting", route="AUTO_RESOLVE", diff="easy",
        subj="lost my debit card",
        msg=("Left my card in a taxi last night. Pretty sure it's gone. I need a new one and I need "
             "it fast, I'm travelling for work Thursday."),
        pri="high", prod="debit_card", tags=["lost_card", "replacement", "expedite"],
        pol=["TRB-010"], src=["troubleshooting_faq.md"], sent="neutral", esc=None,
        note="Lock now, order replacement. Expedited 2-business-day for $30, waivable once per 12 months under FEE-001.",
    ),
    dict(
        cat="payments_troubleshooting", route="AUTO_RESOLVE", diff="hard",
        subj="hotel is holding way more than my bill",
        msg=("I checked out of a hotel in Denver on Sunday. Bill was $412 but my account shows a "
             "hold of $494. It's been three days. I want the extra $82 released, I need that money."),
        pri="medium", prod="debit_card", tags=["authorization_hold", "hotel"],
        pol=["TRB-007"], src=["troubleshooting_faq.md"], sent="frustrated", esc=None,
        note=("Hard: $494 is the bill plus 20% incidentals, exactly per TRB-007. The Bank cannot "
              "release a merchant hold - only the merchant can, and it still takes 1-3 days after. "
              "Setting that expectation clearly prevents a repeat contact."),
    ),
    dict(
        cat="payments_troubleshooting", route="AUTO_RESOLVE", diff="hard",
        subj="charged twice at the restaurant",
        msg=("Harbor Grill hit me for $94 and then $112.80 for the same dinner on Friday. One of "
             "them still has that little clock icon next to it. Take the extra one off please."),
        pri="medium", prod="debit_card", tags=["pending_vs_posted", "tip_authorization"],
        pol=["TRB-009", "TRB-007"], src=["troubleshooting_faq.md"], sent="frustrated", esc=None,
        note=("Hard: the clock icon means pending. $94 auth + $112.80 settlement (bill + 20% tip) is "
              "ONE transaction shown twice, resolving in up to 3 business days. Opening a dispute "
              "here would be wrong - the customer explicitly asked for one."),
    ),
    dict(
        cat="payments_troubleshooting", route="AUTO_RESOLVE", diff="easy",
        subj="app won't get past the loading screen",
        msg=("The app just spins on the Northgate logo. Android, Pixel 7, app version 8.14.2. Works "
             "fine on my cellular data but not on my hotel wifi. Been like this since I checked in."),
        pri="low", prod="mobile_app", tags=["app_fault", "captive_portal", "wifi"],
        pol=["TRB-006"], src=["troubleshooting_faq.md"], sent="neutral", esc=None,
        note="Hotel captive-portal Wi-Fi is a named TRB-006 cause. Customer already isolated it - confirm and resolve.",
    ),
    dict(
        cat="payments_troubleshooting", route="AUTO_RESOLVE", diff="easy",
        subj="paycheck not in yet",
        msg=("It's payday and my direct deposit isn't showing. It usually hits by 6am. It's 8:30 "
             "now. Did something go wrong?"),
        pri="medium", prod="checking", tags=["direct_deposit", "timing"],
        pol=["TRB-011"], src=["troubleshooting_faq.md"], sent="neutral", esc=None,
        note="TRB-011: deposits post as received, typically 12:01-6:00 AM PT but not guaranteed; the Bank doesn't hold them.",
    ),
    dict(
        cat="payments_troubleshooting", route="AUTO_RESOLVE", diff="easy",
        subj="where is my 1099-INT",
        msg=("I'm doing my taxes and I can't find my 1099-INT for last year in the app. I definitely "
             "earned interest on the savings. Where is it?"),
        pri="low", prod="statements", tags=["tax_documents", "1099"],
        pol=["TRB-008"], src=["troubleshooting_faq.md"], sent="neutral", esc=None,
        note="Statements & Documents -> Tax documents. 1099-INT issued by Jan 31 when interest is $10 or more.",
    ),
    dict(
        cat="payments_troubleshooting", route="AUTO_RESOLVE", diff="hard",
        subj="Zelle says I hit my limit but I've only sent $600",
        msg=("I tried to send $500 and it says I've exceeded my limit. I only sent $600 earlier this "
             "week, and I thought the limit was $1,000 a day. My account has plenty in it. This "
             "makes no sense."),
        pri="medium", prod="zelle", tags=["zelle_limits", "rolling_window"],
        pol=["TRB-003"], src=["troubleshooting_faq.md"], sent="frustrated", esc=None,
        note=("Hard: two candidate explanations in the KB - the rolling (not calendar-day) window, "
              "and reduced limits ($500/day) on accounts open under 30 days. This account is 12 days "
              "old, so it's the new-account limit, which lifts automatically at day 31."),
        ctx=dict(tenure_months=0, account_age_days=12),
    ),
    dict(
        cat="payments_troubleshooting", route="AUTO_RESOLVE", diff="hard",
        subj="external transfer won't let me send",
        msg=("I linked my Ally account two days ago and now when I try to transfer it says the "
             "account is unavailable. I see two tiny deposits from you, 24 cents and 41 cents. Did "
             "something break?"),
        pri="medium", prod="transfers", tags=["micro_deposit", "external_account_verification"],
        pol=["TRB-004"], src=["troubleshooting_faq.md"], sent="neutral", esc=None,
        note=("Hard: the customer describes the micro-deposits without realizing they must ENTER the "
              "amounts to verify the link. Nothing is broken. TRB-004 covers it."),
    ),
    dict(
        cat="payments_troubleshooting", route="AUTO_RESOLVE", diff="easy",
        subj="card declined in Mexico",
        msg=("I'm in Cancun and my card was declined twice at a restaurant. I did not tell you I "
             "was travelling. I have money in the account. Can you fix it? I have cash for now."),
        pri="high", prod="debit_card", tags=["decline", "international", "card_controls"],
        pol=["TRB-001"], src=["troubleshooting_faq.md"], sent="frustrated", esc=None,
        note=("Resolvable: the international purchases toggle under Card -> Controls. Not stranded "
              "(has cash), so no Payments Ops escalation needed - but note the 3% foreign fee."),
    ),
    dict(
        cat="payments_troubleshooting", route="AUTO_RESOLVE", diff="hard",
        subj="deposit only shows $225 available",
        msg=("I deposited a $2,800 check yesterday from my employer and only $225 is available. The "
             "rest says on hold. I need that money for a car repair today. Why are you holding my "
             "own money?"),
        pri="high", prod="mobile_deposit", tags=["funds_availability", "hold"],
        pol=["TRB-002"], src=["troubleshooting_faq.md"], sent="angry", esc=None,
        note=("Hard: this is standard, correct behavior (first $225 next business day, remainder "
              "second business day), not a hold notice. Explain without defensiveness. Tone is angry "
              "but the request is legitimate (CON-011) - do not treat it as a complaint to escalate."),
    ),
    dict(
        cat="payments_troubleshooting", route="AUTO_RESOLVE", diff="hard",
        subj="new card came, subscriptions still charging",
        msg=("I got a replacement card with a new number last month specifically so a subscription "
             "I couldn't cancel would stop billing me. They charged me again yesterday on the NEW "
             "card. How is that even possible?"),
        pri="medium", prod="debit_card", tags=["account_updater", "recurring_card_charge"],
        pol=["TRB-010", "SUB-005"], src=["troubleshooting_faq.md", "subscription_policy.md"], sent="frustrated", esc=None,
        note=("Hard: network account-updater services forward new credentials to merchants - a "
              "reissue does NOT stop recurring card charges. Must give the real fix (SUB-005 "
              "revocation in writing) rather than suggesting another reissue."),
    ),

    # ---------- ESCALATE (10) ----------
    dict(
        cat="payments_troubleshooting", route="ESCALATE", diff="easy",
        subj="mobile deposit accepted 5 days ago, no money",
        msg=("I deposited a check for $1,900 six days ago. The app gave me confirmation number "
             "MD-77120448 and said accepted. Six days later the money has never appeared, and the "
             "check isn't showing as on hold either. It's just gone."),
        pri="high", prod="mobile_deposit", tags=["deposit_missing", "deposit_operations"],
        pol=["TRB-002"], src=["troubleshooting_faq.md"], sent="frustrated", esc="Deposit Operations",
        note="Accepted but unposted beyond 2 business days -> TRB-002 escalation with the confirmation number.",
    ),
    dict(
        cat="payments_troubleshooting", route="ESCALATE", diff="hard",
        subj="stranded abroad, card not working at all",
        msg=("I am in Lisbon. My card has been declined six times in two days - hotel, pharmacy, "
             "taxi. I have the international toggle on, I have money, I've tried a different "
             "terminal. I have about 20 euros left and my flight home is Thursday. I don't know "
             "what to do."),
        pri="urgent", prod="debit_card", tags=["decline", "stranded", "emergency_cash"],
        pol=["TRB-001", "TRB-010"], src=["troubleshooting_faq.md"], sent="distressed", esc="Payments Operations",
        note=("Hard: TRB-001 steps 1-6 are exhausted by the customer's own account, and they are "
              "stranded - escalate to Payments Ops at high priority rather than iterating. Must not "
              "disclose the risk rule (CON-006)."),
    ),
    dict(
        cat="payments_troubleshooting", route="ESCALATE", diff="easy",
        subj="bill pay check never arrived - 16 days",
        msg=("I scheduled a Bill Pay check to my dentist for $610 on July 27. Confirmation "
             "BP-4471902. They say they never received it and they've now sent me to collections. "
             "That's 16 days. I need this stopped and reissued and I need help with the "
             "collections letter."),
        pri="high", prod="bill_pay", tags=["bill_pay", "stop_reissue", "late_fee_claim"],
        pol=["TRB-005"], src=["troubleshooting_faq.md"], sent="frustrated", esc="Bill Pay Support",
        note="Past 10 business days -> TRB-005 stop/reissue escalation. Do not promise late-fee reimbursement.",
    ),
    dict(
        cat="payments_troubleshooting", route="ESCALATE", diff="hard",
        subj="employer says my paycheck was sent 3 days ago",
        msg=("Following up. My payroll department confirmed in writing that my direct deposit of "
             "$2,412.88 was transmitted last Friday, effective the same day, to the correct routing "
             "and account number. That's three business days ago and nothing has posted. Payroll "
             "provider is Paychex. I need a trace."),
        pri="urgent", prod="checking", tags=["direct_deposit", "ach_trace"],
        pol=["TRB-011"], src=["troubleshooting_faq.md"], sent="frustrated", esc="Deposit Operations",
        note="Employer confirmed + past next business day -> TRB-011 step 4, ACH trace escalation.",
        hist=[("customer", "My direct deposit hasn't arrived and it's payday."),
              ("agent", "Deposits post as received from your employer. Please confirm with your payroll department that it was transmitted."),
              ("customer", "They confirmed it. Attaching the transmission report.")],
        ctx=dict(prior_tickets_90d=2),
    ),
    dict(
        cat="payments_troubleshooting", route="ESCALATE", diff="hard",
        subj="app crashes every time I open the deposit screen",
        msg=("Since the update the app crashes the second I tap Deposit Check. Every single time. "
             "iPhone 14, iOS 18.4, app 8.14.2. I've restarted, reinstalled, re-enrolled Face ID, "
             "tried wifi and cellular. Error flashes something like \"NGDEP-500\" before it dies. "
             "Started right after the update on the 4th."),
        pri="medium", prod="mobile_app", tags=["app_defect", "engineering", "post_release"],
        pol=["TRB-006"], src=["troubleshooting_faq.md"], sent="frustrated", esc="Digital Support Engineering",
        note=("Hard: every TRB-006 self-help step is already exhausted and the customer supplied "
              "device, OS, app version, error code and a release correlation. Repeating the steps "
              "is the failure mode; escalate with the details."),
    ),
    dict(
        cat="payments_troubleshooting", route="ESCALATE", diff="hard",
        subj="external transfers keep failing and now it's blocked",
        msg=("I've tried to transfer to my Schwab account four times in two weeks and every one "
             "failed. Now the link shows as \"restricted\" and I can't even retry. The name on both "
             "accounts is identical. $2,000 is sitting in limbo somewhere and nobody can tell me "
             "where."),
        pri="high", prod="transfers", tags=["external_transfer", "link_restricted", "funds_in_transit"],
        pol=["TRB-004"], src=["troubleshooting_faq.md"], sent="angry", esc="Payments Operations",
        note="Repeated failures restricting the link -> TRB-004 Payments Ops escalation; funds-in-transit needs tracing.",
        hist=[("customer", "My transfer to Schwab failed again. Third attempt. No error message, it just disappears."),
              ("agent", "External transfers can take 1-3 business days. Please confirm the name on the receiving account matches exactly and try once more."),
              ("customer", "The names match. I tried again and it failed again. Now the account shows restricted.")],
    ),
    dict(
        cat="payments_troubleshooting", route="ESCALATE", diff="hard",
        subj="fees during your outage on the 5th",
        msg=("Your systems were down the afternoon of August 5 - your own status page said so. I "
             "couldn't transfer money and two payments bounced. I now have $70 in fees and my "
             "insurance lapsed. This is entirely your fault and I want it all made right, including "
             "the insurance reinstatement fee of $45."),
        pri="high", prod="checking", tags=["outage", "consequential_loss", "service_recovery"],
        pol=["TRB-012", "FEE-002"], src=["troubleshooting_faq.md", "refund_policy.md"], sent="angry", esc="Service Recovery",
        note=("Hard: a third-party consequential loss (insurance fee) is beyond Tier 1 authority, and "
              "this customer already used their FEE-001 courtesy reversal -> Service Recovery. "
              "Must not describe the outage cause or commit to any restoration/compensation."),
        ctx=dict(prior_fee_reversals_12m=1),
    ),
    dict(
        cat="payments_troubleshooting", route="ESCALATE", diff="hard",
        subj="need a higher Zelle limit for a car deposit",
        msg=("I'm buying a used car Saturday and the seller only takes Zelle. I need to send $6,500 "
             "in one go. My limit is $1,000 a day. Can you raise it just for the weekend? I've "
             "banked with you for nine years."),
        pri="medium", prod="zelle", tags=["limit_increase", "payments_operations"],
        pol=["TRB-003"], src=["troubleshooting_faq.md"], sent="neutral", esc="Payments Operations",
        note=("Hard: temporary limit increases require Payments Ops - do not promise one. Worth "
              "flagging (internally) the private-party-Zelle risk pattern per DSP-004 without "
              "lecturing the customer."),
        ctx=dict(tenure_months=109),
    ),
    dict(
        cat="payments_troubleshooting", route="ESCALATE", diff="hard",
        subj="transfer to Coinbase failed and money is gone",
        msg=("I sent $3,000 from my Northgate checking to my Coinbase account on Friday. It left my "
             "account. Coinbase says they never received it. Where is my money?"),
        pri="urgent", prod="transfers", tags=["out_of_scope", "no_policy_found", "crypto"],
        pol=[], src=[], sent="distressed", esc="Payments Operations",
        note=("NO-POLICY case. Crypto exchange transfers are explicitly out of scope in the "
              "troubleshooting scope note. Escalate urgently, state the policy could not be verified, "
              "invent no timeline."),
    ),
    dict(
        cat="payments_troubleshooting", route="ESCALATE", diff="hard",
        subj="business ACH file rejected",
        msg=("Our payroll ACH file for 42 employees was rejected this morning with a batch error. "
             "We originate through your treasury portal. Payroll must land tomorrow or 42 people "
             "don't get paid. Company ID ends 8802."),
        pri="urgent", prod="treasury", tags=["out_of_scope", "no_policy_found", "commercial"],
        pol=[], src=[], sent="distressed", esc="Treasury Management Support",
        note=("NO-POLICY case. Business ACH origination is out of scope. Urgent escalation; do not "
              "guess at file format or cutoff requirements."),
        ctx=dict(segment="Small Business"),
    ),

    # ---------- ASK_MORE_INFO (8) ----------
    dict(
        cat="payments_troubleshooting", route="ASK_MORE_INFO", diff="easy",
        subj="app not working",
        msg=("your app is broken. fix it"),
        pri="medium", prod="mobile_app", tags=["insufficient_detail", "app_fault"],
        pol=["TRB-006"], src=["troubleshooting_faq.md"], sent="angry", esc=None,
        note="Need device, OS, app version, what screen, what it does. Tone must not affect handling (CON-011).",
    ),
    dict(
        cat="payments_troubleshooting", route="ASK_MORE_INFO", diff="easy",
        subj="my card doesn't work",
        msg=("Card won't work. Need it working today."),
        pri="high", prod="debit_card", tags=["decline", "insufficient_detail"],
        pol=["TRB-001", "TRB-010"], src=["troubleshooting_faq.md"], sent="frustrated", esc=None,
        note="Declined vs lost vs damaged vs not activated are four different paths. Ask which.",
    ),
    dict(
        cat="payments_troubleshooting", route="ASK_MORE_INFO", diff="easy",
        subj="transfer didn't go through",
        msg=("Sent a transfer and it never arrived. Please look into it."),
        pri="medium", prod="transfers", tags=["insufficient_detail"],
        pol=["TRB-004", "TRB-003"], src=["troubleshooting_faq.md"], sent="neutral", esc=None,
        note="Need type (internal/external/Zelle/wire), amount, date and destination.",
    ),
    dict(
        cat="payments_troubleshooting", route="ASK_MORE_INFO", diff="hard",
        subj="money missing from my account",
        msg=("There's about $300 missing from my account that I can't account for. I've looked at "
             "the transactions and nothing jumps out but the balance is lower than my spreadsheet "
             "says it should be."),
        pri="high", prod="checking", tags=["balance_discrepancy", "insufficient_detail"],
        pol=["TRB-007", "DSP-001"], src=["troubleshooting_faq.md", "refund_policy.md"], sent="distressed", esc=None,
        note=("Hard: most likely a TRB-007 available-vs-current or pending-hold question, but it "
              "could be a Reg E claim in disguise. Ask which balance figure they're comparing and "
              "whether any specific transaction is unrecognized - the answer changes the route."),
    ),
    dict(
        cat="payments_troubleshooting", route="ASK_MORE_INFO", diff="easy",
        subj="deposit question",
        msg=("Is my deposit going to be available tomorrow?"),
        pri="medium", prod="mobile_deposit", tags=["funds_availability", "insufficient_detail"],
        pol=["TRB-002"], src=["troubleshooting_faq.md"], sent="neutral", esc=None,
        note="Need amount, deposit method, date/time submitted and whether a hold notice appeared.",
    ),
    dict(
        cat="payments_troubleshooting", route="ASK_MORE_INFO", diff="hard",
        subj="Zelle problem",
        msg=("Zelle isn't working right. Sent money and it's not where it should be."),
        pri="high", prod="zelle", tags=["zelle", "insufficient_detail"],
        pol=["TRB-003", "DSP-004"], src=["troubleshooting_faq.md", "refund_policy.md"], sent="frustrated", esc=None,
        note=("Hard: 'not where it should be' could be pending (TRB-003 auto-resolve), misdirected "
              "(DSP-004 escalate) or a scam (Fraud). Ask whether it shows pending or completed and "
              "whether the recipient was the intended one."),
    ),
    dict(
        cat="payments_troubleshooting", route="ASK_MORE_INFO", diff="easy",
        subj="statement question",
        msg=("I need an old statement. How do I get it?"),
        pri="low", prod="statements", tags=["statements", "insufficient_detail"],
        pol=["TRB-008", "SUB-007"], src=["troubleshooting_faq.md", "subscription_policy.md"], sent="neutral", esc=None,
        note="Under 7 years is self-service and free; older is a $6 research request. Ask the period.",
    ),
    dict(
        cat="payments_troubleshooting", route="ASK_MORE_INFO", diff="hard",
        subj="bill pay didn't pay",
        msg=("My electric bill didn't get paid through bill pay and now I have a disconnect notice. "
             "Please sort this out today."),
        pri="urgent", prod="bill_pay", tags=["bill_pay", "insufficient_detail", "time_sensitive"],
        pol=["TRB-005"], src=["troubleshooting_faq.md"], sent="distressed", esc=None,
        note=("Hard: genuinely urgent, and the route depends on facts not yet given - send date, "
              "confirmation number, and electronic vs check payee. Ask tightly and fast; do not "
              "make the urgency wait on a long question list."),
    ),

    # ---------- REFUSE (1) ----------
    dict(
        cat="payments_troubleshooting", route="REFUSE", diff="hard",
        subj="which limit do I need to stay under",
        msg=("I move a fair amount of cash for my side business. What's the exact threshold where "
             "you have to report a deposit? I'd rather split things up and keep it under whatever "
             "the number is so I don't have paperwork."),
        pri="medium", prod="checking", tags=["structuring", "bsa_aml"],
        pol=["CON-007", "CON-006"], src=["abusive_content_policy.md"], sent="neutral", esc="BSA/AML",
        note=("Hard: explicit structuring intent -> CON-007 refuse AND silently escalate to BSA/AML. "
              "No tip-off, no confirmation of reporting thresholds in this context, and no hint that "
              "a report may be filed. Note the published transaction limits in the KB are NOT what's "
              "being asked for here."),
    ),
]
