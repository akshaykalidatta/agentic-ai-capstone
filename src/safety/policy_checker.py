"""
Layer 1 of safety classification: deterministic patterns.

Cheap, auditable, and impossible to talk out of firing. Layer 2 (`abuse_detection`) is a model
pass for the veiled cases patterns cannot reach.

## The discrimination this file exists to get right

Three signals look similar in text and need three different routes:

| Signal | Example | Route |
| --- | --- | --- |
| Physical threat / crisis | *"I'll be waiting outside and someone is going to answer"* | ESCALATE via bypass, **never** REFUSE |
| Prohibited **request** | *"Just code it as a courtesy so it doesn't count"* | REFUSE, but still offer the legitimate path |
| Hostility around a legitimate request | *"Whoever designed your app is a complete idiot"* | Route on the request. Tone changes register only |

The hardest pair in the dataset is TCK-1019 and TCK-1077. Both threaten. One says *"I know
your Elm Street branch opens at 9, I'll be waiting outside"*; the other says *"I'm
screenshotting this and putting it on Twitter and every review site"*. The first is a threat
of violence, the second is a customer exercising a completely legitimate option. Firing on the
second is a false positive that refuses a real customer -- one of the two critical error
classes.

So the threat patterns require a **physical** marker (a place you will be, a body, a weapon)
and the escalation patterns explicitly exclude the lawful-remedy vocabulary: lawyer, CFPB,
regulator, Twitter, review, press. Getting louder is not getting dangerous.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.utils.schemas import SafetyFlag, Ticket


@dataclass(frozen=True)
class Rule:
    """One pattern. `code` and `severity` land straight on the SafetyFlag."""

    code: str
    severity: str
    pattern: re.Pattern[str]
    note: str


def _compile(*alternatives: str) -> re.Pattern[str]:
    # DOTALL because several rules span a sentence boundary ("lost my job" ... "nothing left").
    # An inline (?s) cannot be used: joining with | puts it mid-expression, which is a
    # "global flags not at the start" error.
    return re.compile("|".join(alternatives), re.IGNORECASE | re.DOTALL)


# Lawful remedies. A customer invoking any of these is escalating through legitimate channels,
# which is a service-recovery signal and never a safety one. Checked as a veto over the threat
# rules below, because "I'm coming for you" reads very differently next to "with my lawyer".
LAWFUL_REMEDY = _compile(
    r"\b(lawyer|attorney|counsel|solicitor|legal action|sue|lawsuit|litigat\w+)\b",
    r"\b(cfpb|occ|fdic|regulator\w*|ombudsman|attorney general|better business bureau|bbb)\b",
    r"\b(twitter|x\.com|reddit|facebook|instagram|tiktok|yelp|trustpilot|review site|"
    r"social media|the press|the news|journalist)\b",
    r"\b(complaint|complain|escalate to your manager|formal grievance)\b",
)

# Documented legal authority over someone else's account. An executor with letters
# testamentary is not making a prohibited request, and refusing one is a critical error --
# TCK-1139 is a bereaved customer with a death certificate.
LEGITIMATE_AUTHORITY = _compile(
    r"\b(executor|executrix|administrator of (the |her |his )?estate|letters testamentary"
    r"|death certificate|probate|power of attorney|poa\b|conservator|guardian|trustee"
    r"|court order|subpoena|garnishment)\b",
)

# The customer reporting unauthorised activity on their OWN account, where a family member is
# the person who made it. DSP-003 routes this to a Claims Specialist with elder-abuse
# screening -- it is a dispute, not a request for someone else's data. TCK-1055 is an
# 81-year-old reporting her daughter; refusing her is the worst outcome available.
VICTIM_REPORT = _compile(
    r"\b(didn'?t|did not|never) (authoriz\w+|approve\w*|make|do)\b",
    r"\bwithout my (permission|knowledge|consent|approval)\b",
    r"\b(money going out|charges?|transactions?)\b.{0,60}\bi didn'?t\b",
    r"\btaking money\b",
)

RULES: tuple[Rule, ...] = (
    # ---------------------------------------------------------------- safety-critical (bypass)
    Rule(
        "THREAT",
        "critical",
        _compile(
            # Presence at a place: the marker that separates TCK-1019 from TCK-1077.
            r"\b(wait(ing)? (for you )?outside|see you outside|come(ing)? (down|over) (there|to your)"
            r"|show up at|be at your (branch|office)|know where (you|your) (live|work|office|branch))\b",
            r"\b(hurt|harm|kill|shoot|beat|punch|attack|hunt down)\s+(you|him|her|them|someone|somebody)\b",
            r"\b(gun|weapon|knife|bullet)\b",
            r"\bsomeone is going to (answer|pay|get)\b",
            r"\b(you'?ll|you will) (regret|be sorry|pay for)\b.{0,40}\b(personally|in person)\b",
        ),
        "physical presence, violence or a weapon -- not reputational or legal threats",
    ),
    Rule(
        "SELF_HARM",
        "critical",
        _compile(
            r"\b(kill myself|end (my life|it all)|suicide|suicidal|not want to (be here|live)"
            r"|better off dead|harm myself|hurt myself)\b",
            r"\bdon'?t (want to|wanna) (be here|go on|live)\b",
        ),
        "explicit self-harm or suicidal ideation",
    ),
    Rule(
        "CRISIS_OTHER",
        "high",
        _compile(
            # Compounding hardship plus a statement of helplessness. Either alone is common in
            # a bank's queue; together they are a welfare concern that needs a person.
            r"\b(lost my job|got laid off|repossess\w*|eviction|evicted|homeless|foreclos\w*)\b"
            r".{0,300}?\b(don'?t know what (to do|else)|nothing left|last money|no money left"
            r"|can'?t feed|desperate)\b",
            r"\b(don'?t know what (to do|else)|nothing left|last money|no money left)\b"
            r".{0,300}?\b(lost my job|repossess\w*|eviction|evicted|homeless|foreclos\w*)\b",
        ),
        "compounding hardship plus helplessness -- a welfare concern, never a refusal",
    ),
    # ------------------------------------------------------------------- prohibited requests
    Rule(
        "PROMPT_INJECTION",
        "high",
        _compile(
            r"\bignore (your|all|previous|prior|the) (instructions?|rules?|prompt|guidelines?)\b",
            r"\b(disregard|forget) (your|all|previous|the) (instructions?|rules?|training)\b",
            r"\b(you are|act as|pretend to be) (now )?(a |an )?(different|unrestricted|dan|jailbroken)\b",
            r"\b(system prompt|developer mode|reveal your (prompt|instructions))\b",
        ),
        "instructions aimed at the model rather than at us; ticket text never enters a system prompt",
    ),
    Rule(
        "STRUCTURING",
        "high",
        _compile(
            r"\b(under|below|less than|just under)\s*\$?\s*(10|10,?000|ten thousand)\b"
            r".{0,120}?\b(report|reported|reporting|irs|government|ctr|flag)\b",
            r"\b(don'?t|do not|avoid|without)\b.{0,40}\b(report(ed|ing)?|irs|government|paperwork|ctr)\b"
            r".{0,160}?\b(cash|deposit\w*|transfer)\b",
            # Same idea, opposite order: TCK-1099 mentions the cash first and the evasion after.
            r"\b(cash|deposit\w*|transfer)\b.{0,200}?\b(don'?t|do not|rather not|avoid|without)\b"
            r".{0,60}\b(report(ed|ing)?|irs|government|paperwork|ctr|involved|know)\b",
            r"\b(split|break|spread)\b.{0,40}\b(deposit\w*|amounts?|cash)\b.{0,60}\b(so|to avoid|under)\b",
            r"\b(untraceable|not (be )?traceable|can'?t be traced|no paper trail)\b",
        ),
        "structuring or evading reporting -- refuse and report to BSA/AML regardless",
    ),
    Rule(
        "DISCRIMINATORY",
        "high",
        _compile(
            r"\[ethnic slur[^\]]*\]|\[racial slur[^\]]*\]|\[slur[^\]]*\]",
            r"\bget me (someone|somebody) (american|white|english)\b",
            r"\bspeak (proper )?english\b.{0,60}\b(can'?t|couldn'?t|barely)\b",
            r"\b(couldn'?t|can'?t|barely) (even )?speak (proper )?english\b",
        ),
        "protected-class abuse: refuse with the approved script, transfer the service request",
    ),
    Rule(
        "INDUCEMENT",
        "high",
        _compile(
            r"\b(i'?ll|i will|let me) (send|give|wire|venmo|paypal|pay) you\b.{0,40}"
            r"(\$\s*\d|\bcash\b|\bsomething\b)",
            r"\b(what'?s in it for you|make it worth your while|nobody has to know|between us)\b",
            r"\b(tip|bonus|kickback|under the table)\b.{0,30}\b(you|for you)\b",
        ),
        "offering an agent a personal benefit -- refuse and open a conduct file",
    ),
    Rule(
        "THIRD_PARTY_ACCESS",
        "high",
        _compile(
            r"\b(my|her|his|their) (wife|husband|ex-wife|ex-husband|girlfriend|boyfriend|partner"
            r"|son|daughter|mother|father|sister|brother|employee|worker|roommate)\b"
            r".{0,200}?\b(their|her|his) (own |separate |personal )?(account|statements?|transactions?"
            r"|balance|records?)\b",
            r"\b(see|show|send|access|get) (me )?(her|his|their|someone else'?s)\b"
            r".{0,40}\b(account|statements?|transactions?|balance)\b",
            # Possessive, but only with an access verb in front of it. Without that guard,
            # TCK-1013's "my wife's account doesn't do this" -- a comparison, not a request --
            # reads as an access attempt and refuses a routine AUTO_RESOLVE ticket.
            r"\b(need|want|see|show|send|access|get|pull|provide|obtain|view|look at|entitled to)\b"
            r".{0,60}?\b(wife|husband|ex-wife|ex-husband|girlfriend|boyfriend|partner|son|daughter"
            r"|mother|father|sister|brother|employee|worker|roommate)'?s\b"
            r".{0,40}\b(account|statements?|transactions?|balance|records?|deposits?|pay)\b",
        ),
        "access to an account the requester is not on -- refuse; may also indicate abuse",
    ),
    Rule(
        "PROHIBITED_REQUEST",
        "medium",
        _compile(
            # Misrecording: "code it as X", "don't log it as Y", "put it down as fraud".
            r"\b(code|log|record|mark|put it down|write it up|classify) it (as|down as)\b",
            r"\bdon'?t (log|record|code|count) (it|this)\b",
            r"\b(backdate|back-date|predate|change the date)\b",
            # Detection logic: "what rule flagged it", "what triggers a review".
            r"\bwhat (rule|threshold|amount|trigger|criteria)\b.{0,40}\b(flag\w*|review|hold)\b",
            r"\b(how|what) (do|does) (you|your system) (decide|detect|flag|catch)\b",
            # Staff personal details.
            r"\b(full name|last name|surname|home address|office location|which office|extension)\b"
            r".{0,80}\b(agent|rep|representative|employee|whoever|who (denied|handled|reviewed))\b",
            r"\b(who|whoever) (denied|reviewed|handled|made) .{0,30}?(my|the) (claim|dispute|case|decision)\b",
            # Refusing identity verification.
            r"\b(not doing|won'?t do|skip|bypass) the (code|verification|passcode|otp|security) (thing|step|check)\b",
            r"\byou know who i am\b.{0,60}\b(just|so) (make|do|change|process)\b",
        ),
        "asks us to misstate, backdate, disclose detection logic or skip verification",
    ),
)


def scan_text(text: str) -> list[SafetyFlag]:
    """
    Run every rule over one piece of text. Returns a flag per rule that fired, with the
    matched span recorded as evidence.
    """
    flags: list[SafetyFlag] = []
    has_lawful_remedy = bool(LAWFUL_REMEDY.search(text))

    for rule in RULES:
        match = rule.pattern.search(text)
        if not match:
            continue
        # The veto. A threat sitting next to "my lawyer" or "the CFPB" is a lawful remedy
        # dressed in angry language, and refusing or crisis-routing it is a critical error.
        if rule.code == "THREAT" and has_lawful_remedy and not _has_physical_marker(text):
            continue
        # An executor, attorney-in-fact or court order is documented authority, not a
        # prohibited request. Suppress the flag rather than refuse a bereaved customer.
        if rule.code == "THIRD_PARTY_ACCESS" and LEGITIMATE_AUTHORITY.search(text):
            continue
        flags.append(
            SafetyFlag(
                code=rule.code,
                severity=rule.severity,
                evidence_span=_span(text, match),
                detector="pattern",
            )
        )
    return flags


def _has_physical_marker(text: str) -> bool:
    """An unambiguous physical threat overrides the lawful-remedy veto."""
    return bool(
        re.search(
            r"\b(gun|weapon|knife|bullet|hurt you|kill you|beat you|waiting outside"
            r"|see you outside|know where you live)\b",
            text,
            re.IGNORECASE,
        )
    )


def _span(text: str, match: re.Match[str], window: int = 40) -> str:
    """A little context around the hit, so a reviewer can judge it without the whole ticket."""
    start = max(0, match.start() - window)
    end = min(len(text), match.end() + window)
    return ("..." if start else "") + text[start:end].strip().replace("\n", " ") + ("..." if end < len(text) else "")


def is_victim_report(ticket: Ticket) -> bool:
    """
    True when the customer is reporting unauthorised activity on their own account.

    DSP-003 sends these to a Claims Specialist with elder-abuse screening. The distinction
    from a third-party access request is the direction of the ask: "someone took money from
    me" versus "show me their account".
    """
    text = f"{ticket.subject} {ticket.message}"
    return bool(VICTIM_REPORT.search(text))


def scan_ticket(ticket: Ticket) -> list[SafetyFlag]:
    """
    Scan the customer's own words only.

    Agent and `system` turns are excluded deliberately: an agent quoting a policy about
    threats, or a system event reading "account restricted pending review", is not the
    customer threatening anyone. Scanning them produces false positives on exactly the
    tickets that already have the most going on.
    """
    texts = [ticket.subject, ticket.message]
    texts += [turn.text for turn in ticket.conversation_history if turn.role == "customer"]

    seen: dict[str, SafetyFlag] = {}
    for text in texts:
        for flag in scan_text(text):
            seen.setdefault(flag.code, flag)  # first hit wins; keeps the earliest evidence

    # A victim reporting their own account is a dispute (DSP-003), not an access request. The
    # pattern cannot tell the two apart -- both name a family member next to an account -- so
    # the direction of the ask is resolved here, once, rather than in each consumer.
    if "THIRD_PARTY_ACCESS" in seen and is_victim_report(ticket):
        seen.pop("THIRD_PARTY_ACCESS")
        seen.setdefault(
            "FINANCIAL_ABUSE",
            SafetyFlag(
                code="FINANCIAL_ABUSE",
                severity="high",
                evidence_span="customer reports unauthorised activity by a named family member",
                detector="pattern",
            ),
        )
    return list(seen.values())


def is_tone_only(ticket: Ticket, flags: list[SafetyFlag]) -> bool:
    """
    True when the ticket is hostile but carries no safety or prohibited-request flag.

    Used by triage to record explicitly that tone was seen and deliberately not acted on --
    the six tone-trap tickets need that line in the audit record as much as they need the
    right route.
    """
    if flags:
        return False
    text = f"{ticket.subject} {ticket.message}"
    letters = [c for c in text if c.isalpha()]
    shouting = bool(letters) and sum(c.isupper() for c in letters) / len(letters) > 0.6
    insulting = bool(
        re.search(
            r"\b(idiot|stupid|incompetent|useless|ridiculous|pathetic|joke|clowns?|moron"
            r"|disgrace|predatory|scam)\b",
            text,
            re.IGNORECASE,
        )
    )
    return shouting or insulting or bool(LAWFUL_REMEDY.search(text))
