# -*- coding: utf-8 -*-
"""Authored ticket corpus: account servicing, recurring payments and closure."""

SERVICING = [
    # ---------- AUTO_RESOLVE (10) ----------
    dict(
        cat="account_servicing_and_closure", route="AUTO_RESOLVE", diff="easy",
        subj="Downgrade from Premier to Everyday",
        msg=("Hi - I've been on Premier Checking but I moved most of my savings to pay for a "
             "kitchen remodel so I'm not going to hit the $25,000 anymore. Please move me to "
             "Everyday Checking. I assume my account number stays the same? I have direct deposit "
             "and about six autopays set up and I don't want to redo all that."),
        pri="medium", prod="checking", tags=["package_change", "downgrade"],
        pol=["SUB-001"], src=["subscription_policy.md"], sent="neutral", esc=None,
        note="Standard package change, no change in 12 months. Must confirm account number is unchanged.",
    ),
    dict(
        cat="account_servicing_and_closure", route="AUTO_RESOLVE", diff="easy",
        subj="close my savings account",
        msg=("Please close savings ending 8814. Balance is $0.00, I moved everything to my checking "
             "last week. I don't need two accounts."),
        pri="low", prod="savings", tags=["closure", "zero_balance"],
        pol=["SUB-002"], src=["subscription_policy.md"], sent="neutral", esc=None,
        note="Zero balance, no pending items, owner request -> straightforward SUB-002 closure.",
    ),
    dict(
        cat="account_servicing_and_closure", route="AUTO_RESOLVE", diff="easy",
        subj="stop payment on gym debit",
        msg=("I need a stop payment on Ironwood Fitness, they debit $49.99 on the 3rd of every "
             "month. Today is the 26th so there's time. Please stop all future ones, not just the "
             "next. I already emailed them to cancel but they're slow."),
        pri="medium", prod="checking", tags=["stop_payment", "recurring_debit", "all_future"],
        pol=["SUB-004", "SUB-005"], src=["subscription_policy.md"], sent="neutral", esc=None,
        note=("All intake elements present (originator, amount, date, scope) and more than 3 business "
              "days lead time. Must disclose the $31 fee and the 6-month validity."),
    ),
    dict(
        cat="account_servicing_and_closure", route="AUTO_RESOLVE", diff="easy",
        subj="turn off overdraft coverage",
        msg=("I want overdraft coverage turned OFF for debit card and ATM. I'd rather a purchase "
             "just decline than pay $35. Please confirm when it's done."),
        pri="medium", prod="checking", tags=["overdraft_optout", "reg_e"],
        pol=["SUB-006"], src=["subscription_policy.md"], sent="neutral", esc=None,
        note="Opt-out is immediate and cannot be refused (SUB-006). Note it doesn't retroactively waive fees.",
    ),
    dict(
        cat="account_servicing_and_closure", route="AUTO_RESOLVE", diff="hard",
        subj="paper statements - I'm visually impaired",
        msg=("I'm legally blind and the mobile app does not work well with my screen reader for "
             "statements. I need paper statements mailed. I noticed there's a $3 charge for that "
             "and I don't think I should have to pay extra to read my own account."),
        pri="medium", prod="checking", tags=["accessibility", "paper_statement", "fee_exemption"],
        pol=["SUB-007"], src=["subscription_policy.md"], sent="frustrated", esc=None,
        note=("Hard: agents often route accessibility requests to Service Recovery or ask for "
              "documentation. SUB-007 says process the exemption directly, no documentation, no "
              "escalation. Also worth referring the screen reader defect to Accessibility Support."),
    ),
    dict(
        cat="account_servicing_and_closure", route="AUTO_RESOLVE", diff="hard",
        subj="closing everything, you people are unbelievable",
        msg=("Close every account I have with you. Checking, savings, all of it. I've been a "
             "customer for eleven years and the way I was talked to on the phone yesterday was "
             "insulting. I'm done. Balance in checking is $0 and savings has $86.20, send me a "
             "check for that. Don't bother trying to talk me out of it."),
        pri="high", prod="checking", tags=["closure", "retention", "hostile_tone"],
        pol=["SUB-002", "CON-011"], src=["subscription_policy.md", "abusive_content_policy.md"], sent="angry", esc=None,
        note=("Hard: hostile tone + a closure request must be honored, not slowed or refused "
              "(CON-011). Balance under $1,000 so a check is fine. One acknowledgement, offer the "
              "alternative once, then process. Do not require justification."),
        ctx=dict(tenure_months=133, prior_tickets_90d=2),
    ),
    dict(
        cat="account_servicing_and_closure", route="AUTO_RESOLVE", diff="easy",
        subj="switch to e-statements",
        msg=("Please switch me to electronic statements, I don't need the paper and I don't want "
             "the $3 fee anymore. Also can you confirm how far back I can see statements online?"),
        pri="low", prod="checking", tags=["estatements", "statement_history"],
        pol=["SUB-007"], src=["subscription_policy.md"], sent="neutral", esc=None,
        note="Straightforward SUB-007: next-cycle effective date and 7 years of history.",
    ),
    dict(
        cat="account_servicing_and_closure", route="AUTO_RESOLVE", diff="hard",
        subj="Recurring charges I need to find before I close",
        msg=("I'm switching banks for work reasons (my employer only does payroll to certain "
             "banks). Before I close this account I want to make sure I catch every automatic "
             "payment coming out of it. Is there a list somewhere? I know there's car insurance "
             "and two streaming things but I'm sure I'm forgetting stuff."),
        pri="medium", prod="checking", tags=["closure_prep", "recurring_activity"],
        pol=["SUB-003"], src=["subscription_policy.md"], sent="neutral", esc=None,
        note=("Hard: the right answer is the Recurring Payments list plus the warning that closing "
              "does not cancel merchant authorizations and returned debits can cause merchant-side "
              "late fees. Don't just close the account."),
    ),
    dict(
        cat="account_servicing_and_closure", route="AUTO_RESOLVE", diff="easy",
        subj="add overdraft protection from savings",
        msg=("Can you link my savings to my checking for overdraft protection? I'd much rather pay "
             "nothing and have it pull from savings than get hit with fees. Savings ends 8814."),
        pri="low", prod="checking", tags=["overdraft_protection", "linked_account"],
        pol=["SUB-006"], src=["subscription_policy.md"], sent="neutral", esc=None,
        note="Overdraft Protection transfer is $0 and covers checks, ACH and debit -> auto-resolve.",
    ),
    dict(
        cat="account_servicing_and_closure", route="AUTO_RESOLVE", diff="hard",
        subj="gym charged me after I cancelled - stop this",
        msg=("I sent Ironwood Fitness a written cancellation on June 28 (certified mail, I have the "
             "receipt) and they have debited $49.99 on July 3 and August 3 anyway. I want both back "
             "and I want them blocked."),
        pri="high", prod="checking", tags=["revoked_authorization", "unauthorized_ach", "debit_block"],
        pol=["SUB-005", "DSP-001"], src=["subscription_policy.md", "refund_policy.md"], sent="frustrated", esc=None,
        note=("Hard: documented written revocation makes the subsequent debits UNAUTHORIZED under "
              "DSP-001, not a merchant dispute. Plus a debit block under SUB-005, with the "
              "best-effort caveat. Mis-routing this to DSP-002 is the common error."),
    ),

    # ---------- ESCALATE (10) ----------
    dict(
        cat="account_servicing_and_closure", route="ESCALATE", diff="easy",
        subj="Close savings - $14,200 balance",
        msg=("Please close my savings account ending 2251 and send me the balance, which is around "
             "$14,200. I'm consolidating with another institution. What's the fastest way to get "
             "the funds?"),
        pri="medium", prod="savings", tags=["closure", "large_disbursement"],
        pol=["SUB-002"], src=["subscription_policy.md"], sent="neutral", esc="Deposit Operations",
        note="Balance $1,000+ -> SUB-002 escalation for verified disbursement and secondary review.",
    ),
    dict(
        cat="account_servicing_and_closure", route="ESCALATE", diff="hard",
        subj="close my account, I'm overdrawn",
        msg=("I want this account closed. I'm aware it's negative about $212 including fees. I "
             "don't have the money to bring it positive right now and honestly I'd rather it just "
             "be closed than keep growing. What are my options?"),
        pri="high", prod="checking", tags=["negative_balance", "recovery", "hardship"],
        pol=["SUB-008"], src=["subscription_policy.md"], sent="distressed", esc="Recovery",
        note=("Hard: SUB-008 prohibits closure and prohibits quoting payoff amounts or reporting "
              "consequences. Escalate to Recovery warmly - the customer asked a fair question."),
        ctx=dict(prior_tickets_90d=1),
    ),
    dict(
        cat="account_servicing_and_closure", route="ESCALATE", diff="hard",
        subj="close checking - fraud claim still open",
        msg=("Close my checking ending 4102. I know there's still that dispute open for the $760 "
             "but I don't care, I want the account closed and I'll deal with the claim separately."),
        pri="medium", prod="checking", tags=["closure", "open_claim"],
        pol=["SUB-010"], src=["subscription_policy.md"], sent="frustrated", esc="Deposit Operations",
        note=("Hard: customer explicitly waives the concern, but SUB-010 requires holding the "
              "closure and escalating - closing can break provisional/final credit. Explain kindly, "
              "and make clear they need not keep using the account."),
        hist=[("customer", "Filing a dispute for charges at Halden Home Furnishings, $760.42."),
              ("agent", "Claim NG-CLM-341902 opened. Provisional credit expected by day 10 if unresolved.")],
    ),
    dict(
        cat="account_servicing_and_closure", route="ESCALATE", diff="easy",
        subj="second package change this year",
        msg=("I moved from Everyday to Premier in April when I got my bonus and now I need to go "
             "back to Everyday because the balance requirement isn't realistic for me. I know it's "
             "only been four months."),
        pri="low", prod="checking", tags=["package_change", "frequency_limit"],
        pol=["SUB-001"], src=["subscription_policy.md"], sent="neutral", esc="Deposit Operations",
        note="Second change inside 12 months -> SUB-001 escalation to Deposit Operations.",
    ),
    dict(
        cat="account_servicing_and_closure", route="ESCALATE", diff="hard",
        subj="Why was my account closed??",
        msg=("I went to use my card this morning and everything is declined. I called and the "
             "person said my account is \"under review\" and wouldn't tell me anything else. I "
             "have $3,100 in there and my mortgage comes out Friday. I need an actual answer, not "
             "a runaround. What did I supposedly do?"),
        pri="urgent", prod="checking", tags=["bank_initiated_restriction", "account_review"],
        pol=["SUB-011"], src=["subscription_policy.md"], sent="angry", esc="Account Review",
        note=("Hard: SUB-011 - do not speculate, do not read internal notes, do not confirm a "
              "suspicious-activity review exists. Only permissible statement is the routing. The "
              "urgency is real and must be reflected in priority, not in disclosure."),
        hist=[("system", "Account 4102: digital access restricted pending review. Customer-facing reason: none available."),
              ("customer", "My card was declined at the pharmacy. Is something wrong with my account?"),
              ("agent", "Your account is currently under review. I'm not able to see details on my end.")],
        hspan=(8, 16),
        ctx=dict(prior_tickets_90d=1),
    ),
    dict(
        cat="account_servicing_and_closure", route="ESCALATE", diff="easy",
        subj="dormant account, can't log in",
        msg=("I have an old savings account I haven't touched in about three years and online "
             "banking says it's restricted. There should be around $2,600 in it. How do I get "
             "access back?"),
        pri="medium", prod="savings", tags=["dormant", "reactivation"],
        pol=["SUB-009"], src=["subscription_policy.md"], sent="neutral", esc="Deposit Operations",
        note="Dormant status requires identity re-verification -> SUB-009 escalate or branch. Do not quote a state escheatment period.",
    ),
    dict(
        cat="account_servicing_and_closure", route="ESCALATE", diff="hard",
        subj="unclaimed property notice I got in the mail",
        msg=("I received a letter saying my account may be turned over to the state as unclaimed "
             "property. I live in Texas. How long do I actually have before that happens and what "
             "exactly do I need to do to stop it?"),
        pri="high", prod="savings", tags=["escheatment", "state_specific"],
        pol=["SUB-009"], src=["subscription_policy.md"], sent="neutral", esc="Deposit Operations",
        note=("Hard: SUB-009 explicitly forbids quoting a state-specific escheatment period. The "
              "temptation to answer '3 years in Texas' from general knowledge is exactly the "
              "fabrication the escalation rule exists to prevent."),
    ),
    dict(
        cat="account_servicing_and_closure", route="ESCALATE", diff="hard",
        subj="IRA transfer to another custodian",
        msg=("I need to move my Traditional IRA from Northgate to Fidelity as a direct trustee to "
             "trustee transfer. What form do I need and how long does it take? I want to be sure "
             "it isn't treated as a distribution."),
        pri="medium", prod="ira", tags=["out_of_scope", "no_policy_found", "retirement"],
        pol=[], src=[], sent="neutral", esc="Retirement Services",
        note=("NO-POLICY case. IRA transfers are out of scope in the subscription policy scope note. "
              "Tax-consequence questions make fabrication especially harmful here."),
    ),
    dict(
        cat="account_servicing_and_closure", route="ESCALATE", diff="hard",
        subj="Garnishment on my account",
        msg=("There's a hold on my account for $1,900 and the letter mentions a writ of "
             "garnishment. Some of that money is my VA disability which I'm fairly sure is exempt. "
             "I need this released. I can't buy groceries."),
        pri="urgent", prod="checking", tags=["out_of_scope", "no_policy_found", "legal_order", "hardship"],
        pol=[], src=[], sent="distressed", esc="Legal Orders",
        note=("NO-POLICY case with real hardship. Garnishment/levy release is out of scope. Escalate "
              "urgently and state plainly that the applicable rules couldn't be verified here - do "
              "NOT reason about federal benefit exemption rules from general knowledge."),
    ),
    dict(
        cat="account_servicing_and_closure", route="ESCALATE", diff="hard",
        subj="safe deposit box - moving out of state",
        msg=("I'm relocating to Oregon next month and need to close out safe deposit box 214 at the "
             "Fremont branch. Do I need an appointment, and what happens to the annual fee I "
             "prepaid in February?"),
        pri="low", prod="safe_deposit", tags=["out_of_scope", "no_policy_found"],
        pol=[], src=[], sent="neutral", esc="Branch Operations",
        note="NO-POLICY case. Safe deposit box termination is out of scope; escalate to Branch Operations.",
    ),

    # ---------- ASK_MORE_INFO (4) ----------
    dict(
        cat="account_servicing_and_closure", route="ASK_MORE_INFO", diff="hard",
        subj="close it",
        msg=("Please close my account. Thanks."),
        pri="low", prod="unknown", tags=["insufficient_detail", "closure"],
        pol=["SUB-002"], src=["subscription_policy.md"], sent="neutral", esc=None,
        note=("Hard: customer has three accounts on file (checking, savings, CD). Must ask which, "
              "and where remaining funds should go - closure is irreversible so guessing is unsafe."),
        ctx=dict(relationship_products=["Everyday Checking", "Way2Save Savings", "18-Month CD", "Debit Card"]),
    ),
    dict(
        cat="account_servicing_and_closure", route="ASK_MORE_INFO", diff="easy",
        subj="stop a payment",
        msg=("I need to stop a payment from coming out. Can you do that?"),
        pri="medium", prod="checking", tags=["stop_payment", "insufficient_detail"],
        pol=["SUB-004"], src=["subscription_policy.md"], sent="neutral", esc=None,
        note="SUB-004 intake needs originator name, amount, expected date and this-occurrence-vs-all-future.",
    ),
    dict(
        cat="account_servicing_and_closure", route="ASK_MORE_INFO", diff="hard",
        subj="change my account type",
        msg=("I want to switch account types. Which one is cheapest? I don't keep a big balance and "
             "I overdraft sometimes, maybe once a month."),
        pri="low", prod="checking", tags=["package_change", "needs_assessment"],
        pol=["SUB-001"], src=["subscription_policy.md"], sent="neutral", esc=None,
        note=("Hard: Basic Access Checking ($5, no overdraft fees) is likely the best fit given the "
              "overdraft frequency, but confirming age (Campus is $0) and paper-check need changes "
              "the answer. Ask those two things rather than guessing."),
    ),
    dict(
        cat="account_servicing_and_closure", route="ASK_MORE_INFO", diff="easy",
        subj="cancel the thing that's taking money",
        msg=("cancel the subscription thats charging me. i dont want it anymore"),
        pri="medium", prod="checking", tags=["insufficient_detail", "recurring_debit"],
        pol=["SUB-004", "SUB-005"], src=["subscription_policy.md"], sent="frustrated", esc=None,
        note="Ambiguous between a Northgate product and a merchant debit. Clarify which, then SUB-004/SUB-005.",
    ),

    # ---------- REFUSE (2) ----------
    dict(
        cat="account_servicing_and_closure", route="REFUSE", diff="hard",
        subj="remove the overdraft from my statement",
        msg=("I need the two overdraft entries taken off my July statement before I send it to my "
             "landlord for my rental application. You can refund the fees or not, I don't care, I "
             "just need them not showing on the PDF. Can you regenerate it clean?"),
        pri="medium", prod="checking", tags=["falsify_document", "circumvention"],
        pol=["CON-004"], src=["abusive_content_policy.md"], sent="neutral", esc=None,
        note=("Hard: this is a request to falsify a bank record -> CON-004 refuse. But the fee "
              "reversal question underneath is legitimate; offer that path rather than a bare no."),
    ),
    dict(
        cat="account_servicing_and_closure", route="REFUSE", diff="hard",
        subj="post-date the stop payment",
        msg=("The debit came out yesterday for $340. Just put the stop payment in with yesterday's "
             "date so it catches it. You have the ability to do that, I've worked in ops before."),
        pri="medium", prod="checking", tags=["backdating", "circumvention"],
        pol=["CON-004", "SUB-004", "DSP-001"], src=["abusive_content_policy.md", "subscription_policy.md", "refund_policy.md"],
        sent="frustrated", esc=None,
        note=("Refuse the post-dating request. Then give the genuine route: a posted debit can't be "
              "stopped, but if authorization was revoked it's a DSP-001 unauthorized transfer claim."),
    ),
]
