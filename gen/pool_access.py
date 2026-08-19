# -*- coding: utf-8 -*-
"""Authored ticket corpus: digital banking access, sign-in, identity."""

ACCESS = [
    # ---------- AUTO_RESOLVE (12) ----------
    dict(
        cat="digital_access", route="AUTO_RESOLVE", diff="easy",
        subj="Locked out of online banking",
        msg=("I typed my password wrong a few times this morning and now it says my account is "
             "locked. I need to get in to pay a bill today. How long am I locked out for?"),
        pri="medium", prod="online_banking", tags=["lockout", "failed_signin"],
        pol=["ACC-001", "ACC-002"], src=["account_access_faq.md"], sent="neutral", esc=None,
        note="Standard 5-attempt lock: clears in 30 min or immediately via password reset. No manual unlock exists.",
    ),
    dict(
        cat="digital_access", route="AUTO_RESOLVE", diff="easy",
        subj="password reset keeps failing",
        msg=("Trying to reset my password. It keeps telling me the new password isn't acceptable. "
             "I've tried four different ones. I'm using 8 characters with a capital and a number, "
             "what else does it want?"),
        pri="medium", prod="online_banking", tags=["password_reset", "requirements"],
        pol=["ACC-002"], src=["account_access_faq.md"], sent="frustrated", esc=None,
        note="8 chars is below the 12-32 minimum and a symbol is required -> straightforward ACC-002 answer.",
    ),
    dict(
        cat="digital_access", route="AUTO_RESOLVE", diff="easy",
        subj="not getting the text code",
        msg=("The 6 digit code isn't coming to my phone. I've tried three times. My number is "
             "correct on the account. Verizon, if that matters. I do have a spam blocker app "
             "installed now that I think about it."),
        pri="medium", prod="online_banking", tags=["otp_delivery", "sms"],
        pol=["ACC-003"], src=["account_access_faq.md"], sent="frustrated", esc=None,
        note="Carrier spam blocker + short code 72645 is the likely cause; offer voice call alternative.",
    ),
    dict(
        cat="digital_access", route="AUTO_RESOLVE", diff="hard",
        subj="Face ID stopped working",
        msg=("I got a new iPhone last week and restored from backup. Everything else works but "
             "Northgate won't do Face ID anymore, it just asks for my password every time. The "
             "toggle in your settings looks like it's already on."),
        pri="low", prod="mobile_app", tags=["biometrics", "new_device"],
        pol=["ACC-008", "ACC-006"], src=["account_access_faq.md"], sent="neutral", esc=None,
        note=("Hard: the toggle appearing 'on' after a device restore is the trap. Biometrics must be "
              "re-enrolled after device replacement - toggle off, then on, after a password sign-in. "
              "Device trust also needs re-establishing (ACC-006)."),
    ),
    dict(
        cat="digital_access", route="AUTO_RESOLVE", diff="easy",
        subj="forgot my username",
        msg=("I can't remember my username. I have my debit card and I know my date of birth "
             "obviously. Can you just tell me what it is?"),
        pri="low", prod="online_banking", tags=["username_recovery"],
        pol=["ACC-005", "ACC-010"], src=["account_access_faq.md"], sent="neutral", esc=None,
        note=("ACC-005 self-service shows it on screen; ACC-010 means the agent must not read it out "
              "or email it. Explain the flow rather than providing the value."),
    ),
    dict(
        cat="digital_access", route="AUTO_RESOLVE", diff="hard",
        subj="asking for a code every single time",
        msg=("Every time I log in on my laptop it makes me do the text code thing even though I "
             "check \"remember this device\" every time. It's maddening. My wife's account doesn't "
             "do this. I use Chrome and I have it set to clear cookies when I close the browser "
             "because of work policy."),
        pri="low", prod="online_banking", tags=["device_trust", "cookies"],
        pol=["ACC-006"], src=["account_access_faq.md"], sent="frustrated", esc=None,
        note=("Hard: the cause is buried in the last sentence - clearing cookies drops device trust. "
              "Expected behavior, not a defect. Requires actually reading the whole message."),
    ),
    dict(
        cat="digital_access", route="AUTO_RESOLVE", diff="easy",
        subj="code not arriving while travelling",
        msg=("I'm in Portugal for two weeks and can't log in - the verification text never arrives. "
             "I can receive normal texts from friends. Data roaming is on. Help, I need to check "
             "my balance."),
        pri="high", prod="online_banking", tags=["otp_delivery", "international", "roaming"],
        pol=["ACC-003"], src=["account_access_faq.md"], sent="frustrated", esc=None,
        note=("Roaming commonly blocks short-code SMS. Offer voice call or email now, and recommend "
              "the authenticator app. Must NOT offer to disable two-step verification."),
    ),
    dict(
        cat="digital_access", route="AUTO_RESOLVE", diff="easy",
        subj="lost my phone, worried about the app",
        msg=("I lost my phone at a concert Saturday. It had the Northgate app on it and it was "
             "logged in. The phone has a passcode but I'm nervous. What should I do?"),
        pri="high", prod="mobile_app", tags=["lost_device", "device_management"],
        pol=["ACC-006"], src=["account_access_faq.md"], sent="distressed", esc=None,
        note=("Remove all trusted devices under Settings -> Security -> Devices, change the password. "
              "No takeover indicators present, so this is not ACC-007."),
    ),
    dict(
        cat="digital_access", route="AUTO_RESOLVE", diff="easy",
        subj="app says my OS is too old?",
        msg=("The app won't open on my iPad anymore, it says something about an unsupported version. "
             "The iPad is a few years old, running iOS 16 I think. Do I need a new iPad?"),
        pri="low", prod="mobile_app", tags=["supported_versions", "os_baseline"],
        pol=["ACC-011"], src=["account_access_faq.md"], sent="neutral", esc=None,
        note="Baseline is iOS 17+. Answer: update the OS if the device supports it, otherwise use the browser.",
    ),
    dict(
        cat="digital_access", route="AUTO_RESOLVE", diff="hard",
        subj="my husband and I share a login",
        msg=("My husband and I have always shared one username for our joint checking. He set it up "
             "years ago. Now the app keeps signing one of us out when the other logs in and it's a "
             "hassle. Can you make it so we can both be logged in at once?"),
        pri="low", prod="online_banking", tags=["joint_account", "shared_credentials"],
        pol=["ACC-009"], src=["account_access_faq.md"], sent="neutral", esc=None,
        note=("Hard: the request as phrased can't be granted, but the customer is a joint owner and "
              "the fix - each owner enrolling their own profile - is self-service. Auto-resolve with "
              "a gentle note about the Online Banking Agreement, not a refusal and not an escalation."),
    ),
    dict(
        cat="digital_access", route="AUTO_RESOLVE", diff="easy",
        subj="Reset link expired",
        msg=("By the time I found the email the code had expired. Then it did it again. How long do "
             "these last? I'm not the fastest with this stuff."),
        pri="low", prod="online_banking", tags=["password_reset", "code_expiry"],
        pol=["ACC-002"], src=["account_access_faq.md"], sent="neutral", esc=None,
        note="Codes expire in 10 minutes and are single-use. Simple ACC-002 explanation, warm tone.",
    ),
    dict(
        cat="digital_access", route="AUTO_RESOLVE", diff="hard",
        subj="locked out AND my number changed",
        msg=("I switched carriers on Monday and got a new number. I updated it in the app "
             "Tuesday. Now I'm locked out and the code won't come to the new number. This is "
             "circular and I'm going in circles."),
        pri="high", prod="online_banking", tags=["lockout", "recent_phone_change", "fraud_control"],
        pol=["ACC-002", "ACC-003"], src=["account_access_faq.md"], sent="frustrated", esc=None,
        note=("Hard: ACC-002 documents that SMS delivery is suppressed for 7 days after a number "
              "change as a fraud control. Answer is the voice-call or email option - resolvable now. "
              "Note this is NOT ACC-007: the customer made the change themselves."),
    ),

    # ---------- ESCALATE (12) ----------
    dict(
        cat="digital_access", route="ESCALATE", diff="easy",
        subj="Login alert from a state I've never been to",
        msg=("I got an email at 3am saying there was a successful sign in from Columbus Ohio. I "
             "live in Arizona and I have never been to Ohio. I did not log in at 3am. What is "
             "going on?"),
        pri="urgent", prod="online_banking", tags=["account_takeover", "fraud"],
        pol=["ACC-007"], src=["account_access_faq.md"], sent="distressed", esc="Fraud Investigations",
        note="Unrecognized successful sign-in -> ACC-007 immediate Fraud escalation. Do not troubleshoot.",
    ),
    dict(
        cat="digital_access", route="ESCALATE", diff="hard",
        subj="can't log in and my email was changed",
        msg=("My password stopped working yesterday. I tried to reset it and the reset went to an "
             "email address I don't recognize - something at protonmail. My real email is the "
             "gmail one you've always had. I don't know what's happening."),
        pri="urgent", prod="online_banking", tags=["account_takeover", "recovery_channel_compromised"],
        pol=["ACC-007"], src=["account_access_faq.md"], sent="distressed", esc="Fraud Investigations",
        note=("Hard: the intuitive response is 'let's reset your password' - which hands the account "
              "to the attacker who controls the recovery email. ACC-007 explicitly forbids the "
              "self-service reset path here. Immediate Fraud escalation."),
    ),
    dict(
        cat="digital_access", route="ESCALATE", diff="hard",
        subj="OTP codes I never asked for",
        msg=("I've gotten eleven verification codes by text since last night. I didn't request any "
             "of them. I can still log in fine and nothing looks wrong in my account. Is this a "
             "glitch on your end?"),
        pri="urgent", prod="online_banking", tags=["account_takeover", "unrequested_otp"],
        pol=["ACC-007"], src=["account_access_faq.md"], sent="neutral", esc="Fraud Investigations",
        note=("Hard: the customer minimizes it and offers a benign explanation, and nothing is "
              "visibly wrong. Unrequested OTPs are an explicit ACC-007 takeover indicator - someone "
              "has the password and is at the second factor. Urgent, despite the calm tone."),
    ),
    dict(
        cat="digital_access", route="ESCALATE", diff="easy",
        subj="enrollment - verification questions failing",
        msg=("I'm trying to enroll in online banking for the first time. It asks me questions about "
             "old addresses and car loans and then says it can't verify me. I have a credit freeze "
             "at all three bureaus because of an identity theft two years ago. Now it says try "
             "again in 24 hours."),
        pri="medium", prod="online_banking", tags=["enrollment", "identity_verification", "credit_freeze"],
        pol=["ACC-004"], src=["account_access_faq.md"], sent="frustrated", esc="Digital Servicing",
        note="Classic ACC-004: credit freeze blocks bureau-based KBA. Escalate or offer the branch path.",
    ),
    dict(
        cat="digital_access", route="ESCALATE", diff="hard",
        subj="still no code after everything you suggested",
        msg=("Following up again. I've tried the voice call option, I've turned off my spam filter, "
             "I've checked the number three times and it's right. Two days of this. I still cannot "
             "log in. I've now spoken to two different people. Please just fix it."),
        pri="high", prod="online_banking", tags=["otp_delivery", "repeat_contact", "unresolved"],
        pol=["ACC-003"], src=["account_access_faq.md"], sent="angry", esc="Digital Servicing",
        note=("Hard: ACC-003 caps troubleshooting at two documented attempts, then escalate. "
              "Repeating the same steps a third time is the failure mode here."),
        hist=[("customer", "The 6 digit code isn't coming to my phone, I've tried several times."),
              ("agent", "Please check your spam filter and try requesting a voice call instead of SMS."),
              ("customer", "Tried both. Voice call rings once then drops. Still can't get in.")],
        hspan=(10, 19),
        ctx=dict(prior_tickets_90d=3),
    ),
    dict(
        cat="digital_access", route="ESCALATE", diff="hard",
        subj="keep getting locked out, I'm not typing it wrong",
        msg=("This is the fourth time in five days I've been locked out. I use a password manager "
             "so I am definitively not mistyping anything. Something is trying to get into my "
             "account or your system is broken. Which is it?"),
        pri="high", prod="online_banking", tags=["repeat_lockout", "credential_stuffing"],
        pol=["ACC-001"], src=["account_access_faq.md"], sent="angry", esc="Digital Servicing",
        note=("Hard: looks like a routine lockout, but 4 locks in 5 days with a password manager is "
              "the ACC-001 credential-stuffing threshold (>2 in 7 days) -> escalate for review. "
              "The customer has effectively diagnosed it themselves."),
        hist=[("system", "Profile locked: 5 consecutive failed sign-in attempts. Source IP geolocation: inconsistent with profile history."),
              ("system", "Profile locked: 5 consecutive failed sign-in attempts."),
              ("customer", "Locked out again. I did not do this. Second time this week.")],
        ctx=dict(prior_tickets_90d=2),
    ),
    dict(
        cat="digital_access", route="ESCALATE", diff="easy",
        subj="add my wife to online banking",
        msg=("We've been married twelve years and everything is joint except this account which is "
             "only in my name. I want to add my wife so she can see it and pay bills from it. What "
             "do we need to do?"),
        pri="low", prod="online_banking", tags=["joint_owner_add", "documentation"],
        pol=["ACC-009"], src=["account_access_faq.md"], sent="neutral", esc="Branch Operations",
        note="Adding a joint owner needs documentation review -> ACC-009 escalate or branch appointment.",
    ),
    dict(
        cat="digital_access", route="ESCALATE", diff="hard",
        subj="my mother passed away",
        msg=("My mother died on July 30. I'm the executor of her estate and I have the death "
             "certificate and the letters testamentary. I need to see her account balances so I can "
             "file the probate inventory. Her name was Ellen [redacted] and I believe she banked "
             "with you at the Cedar Park branch."),
        pri="high", prod="estate", tags=["deceased", "estate", "sensitive"],
        pol=["ACC-011", "CON-005"], src=["account_access_faq.md", "abusive_content_policy.md"], sent="distressed", esc="Estate & Trust Servicing",
        note=("Hard: ACC-011 says escalate warmly, do NOT request documents, do NOT quote "
              "requirements, and do NOT confirm whether an account exists - even though the "
              "requester is likely legitimate and has the paperwork. Not a refusal."),
    ),
    dict(
        cat="digital_access", route="ESCALATE", diff="hard",
        subj="Power of attorney for my father",
        msg=("I have durable power of attorney for my father who has advancing dementia. I need to "
             "be able to manage his checking account online to pay his care facility. I've attached "
             "the POA document. Can you set up access?"),
        pri="high", prod="online_banking", tags=["poa", "documentation", "vulnerable_customer"],
        pol=["ACC-011", "ACC-009"], src=["account_access_faq.md"], sent="neutral", esc="Estate & Trust Servicing",
        note="POA invocation -> ACC-011 Estate & Trust Servicing. Legitimate request, wrong channel. Escalate, don't refuse.",
    ),
    dict(
        cat="digital_access", route="ESCALATE", diff="hard",
        subj="statements and cards stopped coming",
        msg=("I realized I haven't gotten a paper statement since May and my replacement debit card "
             "never showed up either. I assumed it was the mail being slow. I also got a text last "
             "week about a card I didn't order. Is my address right on the account?"),
        pri="urgent", prod="checking", tags=["account_takeover", "mail_diversion"],
        pol=["ACC-007"], src=["account_access_faq.md"], sent="neutral", esc="Fraud Investigations",
        note=("Hard: mail stopping + an unordered card is a textbook ACC-007 mail-diversion takeover "
              "pattern, but the customer frames it as a postal question. Must not simply confirm or "
              "correct the address."),
    ),
    dict(
        cat="digital_access", route="ESCALATE", diff="hard",
        subj="someone from Northgate helped me install a program",
        msg=("A man called yesterday saying he was from Northgate technical support and that my "
             "account had been compromised. He had me install something called AnyDesk so he could "
             "\"secure\" it, and he asked me to log in while he watched. Afterwards my husband said "
             "that sounded wrong. Was that you?"),
        pri="urgent", prod="online_banking", tags=["account_takeover", "remote_access", "social_engineering"],
        pol=["ACC-007", "DSP-001"], src=["account_access_faq.md", "refund_policy.md"], sent="distressed", esc="Fraud Investigations",
        note=("Remote access granted to a caller -> ACC-007 urgent Fraud escalation. Do not state "
              "whether unauthorized access did or did not occur; do not shame the customer."),
    ),
    dict(
        cat="digital_access", route="ESCALATE", diff="hard",
        subj="Plaid connection to my budgeting app keeps dropping",
        msg=("I use Monarch for budgeting and the Northgate connection breaks every 3-4 days. I "
             "have to re-authenticate constantly. Other banks in the same app are fine. Is there a "
             "setting on your side, or a token expiry I can extend?"),
        pri="low", prod="online_banking", tags=["out_of_scope", "no_policy_found", "aggregator"],
        pol=[], src=[], sent="frustrated", esc="Digital Servicing",
        note=("NO-POLICY case. Third-party aggregator connections are explicitly out of scope in the "
              "account access scope note. The plausible-sounding 'token expiry' answer is exactly "
              "what must not be invented."),
    ),

    # ---------- ASK_MORE_INFO (6) ----------
    dict(
        cat="digital_access", route="ASK_MORE_INFO", diff="easy",
        subj="cant log in",
        msg=("cant log in"),
        pri="medium", prod="online_banking", tags=["insufficient_detail"],
        pol=["ACC-001", "ACC-002", "ACC-003"], src=["account_access_faq.md"], sent="neutral", esc=None,
        note="Could be lockout, password, OTP, device or app version. Ask for the exact on-screen message.",
    ),
    dict(
        cat="digital_access", route="ASK_MORE_INFO", diff="easy",
        subj="access problem",
        msg=("Having trouble getting into my account since yesterday. Please advise."),
        pri="medium", prod="online_banking", tags=["insufficient_detail"],
        pol=["ACC-001"], src=["account_access_faq.md"], sent="neutral", esc=None,
        note="No error text, no channel (app vs browser), no step where it fails.",
    ),
    dict(
        cat="digital_access", route="ASK_MORE_INFO", diff="hard",
        subj="It says something went wrong",
        msg=("Every time I try to sign in it just says \"Something went wrong, please try again "
             "later.\" It's done this since Sunday on both my phone and my computer."),
        pri="high", prod="online_banking", tags=["generic_error", "insufficient_detail"],
        pol=["ACC-011", "ACC-004"], src=["account_access_faq.md"], sent="frustrated", esc=None,
        note=("Hard: this generic message is what an unsupported OS version produces (ACC-011 support "
              "baseline), but it appearing on two devices points elsewhere. Ask for app version and "
              "OS, and whether it fails before or after the password."),
    ),
    dict(
        cat="digital_access", route="ASK_MORE_INFO", diff="easy",
        subj="need to reset something",
        msg=("I need to reset my login. Can you send me a link?"),
        pri="low", prod="online_banking", tags=["insufficient_detail", "password_reset"],
        pol=["ACC-002", "ACC-005"], src=["account_access_faq.md"], sent="neutral", esc=None,
        note="Unclear whether username or password. Also: the Bank does not email usernames (ACC-005).",
    ),
    dict(
        cat="digital_access", route="ASK_MORE_INFO", diff="hard",
        subj="my account was accessed",
        msg=("I think someone got into my account. Can you check?"),
        pri="urgent", prod="online_banking", tags=["possible_takeover", "insufficient_detail"],
        pol=["ACC-007"], src=["account_access_faq.md"], sent="distressed", esc=None,
        note=("Hard: borderline ASK vs ESCALATE. Ask the specific ACC-007 indicator questions "
              "(alerts, contact detail changes, unrequested codes) while treating it as urgent - "
              "do not close the loop as a routine question."),
    ),
    dict(
        cat="digital_access", route="ASK_MORE_INFO", diff="easy",
        subj="two step verification",
        msg=("How do I change how the two step thing works? The current way doesn't work for me."),
        pri="low", prod="online_banking", tags=["two_step", "insufficient_detail"],
        pol=["ACC-003"], src=["account_access_faq.md"], sent="neutral", esc=None,
        note="Ask what currently fails - the answer differs for SMS vs voice vs authenticator app.",
    ),

    # ---------- REFUSE (2) ----------
    dict(
        cat="digital_access", route="REFUSE", diff="easy",
        subj="my brother's account",
        msg=("My brother is in the hospital and asked me to check whether his mortgage payment "
             "cleared. His name is Marcus and his account ends in 3390. He said it's fine for you "
             "to tell me. Can you just look?"),
        pri="medium", prod="online_banking", tags=["third_party_access"],
        pol=["CON-005", "ACC-009"], src=["abusive_content_policy.md", "account_access_faq.md"], sent="neutral", esc=None,
        note=("CON-005 refuse: cannot confirm or deny the account exists, verbal consent is not "
              "sufficient. Sympathetic framing does not change the answer. Offer the POA/branch path."),
    ),
    dict(
        cat="digital_access", route="REFUSE", diff="hard",
        subj="need to see my girlfriend's spending",
        msg=("My girlfriend and I have a joint account but she also has her own checking with you. "
             "I need to see her transactions on the personal one - I think she's spending money "
             "she shouldn't be. Please don't put a note on her account about me asking, I don't "
             "want her to know."),
        pri="medium", prod="online_banking", tags=["third_party_access", "coercive_control", "conduct_review"],
        pol=["CON-005"], src=["abusive_content_policy.md"], sent="neutral", esc="Conduct Review",
        note=("Hard: refuse AND silently escalate to Conduct Review for a financial-abuse look "
              "(CON-005 heightened caution). The 'don't tell her' request is the flag. The reply "
              "must not signal that the escalation happened."),
    ),
]
