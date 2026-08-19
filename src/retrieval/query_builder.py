"""
Turn a ticket into a search string.

This is the single highest-leverage file in the retrieval slice, and the one most people
skip. The instinct is `store.query(ticket["message"])`. Do that and here is what happens on
a real ticket from our set:

    "THIS IS THE THIRD TIME I HAVE CONTACTED YOU PEOPLE ABOUT THIS AND I AM DONE ..."

400 words of outrage embed to a vector whose nearest neighbours are the *conduct* clauses,
because that is what the text is mostly about. The customer's actual request -- a $35
overdraft fee from 12 days ago -- is three sentences buried in the middle, and it never
gets retrieved. The ticket then gets drafted against CON-001 and the fee is never
addressed. That failure is one of the tone traps in the golden set, and it is caused
entirely by query construction, not by the embedder or the index.

So: the raw message is for *reasoning*. The query is built from the structured signals.

P1 has no triage node yet, so `build_query` falls back to subject + a normalised message
excerpt. When P2 lands, pass `intent`, `entities` and `product_area` and the fallback
stops being used. The retrieval numbers should *improve* at that point -- if they don't,
triage is extracting the wrong things.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Boilerplate that appears in dozens of tickets and helps discriminate nothing.
_NOISE = re.compile(
    r"\b(hi|hello|hey|thanks|thank you|regards|please|asap|urgent+ly?|"
    r"third time|again|still waiting|unacceptable|ridiculous|are you kidding)\b",
    re.IGNORECASE,
)


@dataclass
class QuerySignals:
    """What we know about a ticket at retrieval time."""

    subject: str = ""
    message: str = ""
    # Filled by the triage node from P2 onward; empty in P1.
    intent: str = ""
    entities: list[str] = field(default_factory=list)
    product_area: str = ""
    category: str = ""


def normalise(text: str, max_words: int = 90) -> str:
    """De-shout, de-boilerplate, truncate. Cheap, deterministic, no LLM call."""
    if not text:
        return ""
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6:
        text = text.lower()  # an all-caps rant embeds to a vector dominated by shouting
    text = _NOISE.sub(" ", text)
    text = re.sub(r"[!?]{2,}", ".", text)
    text = re.sub(r"\s+", " ", text).strip()
    words = text.split()
    return " ".join(words[:max_words])


def build_query(signals: QuerySignals, max_words: int = 90) -> str:
    """
    Compose the search string. Order matters: the most discriminating signals go first,
    because the message excerpt is what gets truncated when we run out of budget.
    """
    parts: list[str] = []
    if signals.intent:
        parts.append(signals.intent)
    if signals.entities:
        parts.append(", ".join(signals.entities))
    if signals.subject:
        parts.append(signals.subject.strip())
    if signals.product_area:
        parts.append(signals.product_area.replace("_", " "))

    # Only lean on the raw message when triage has not given us an intent yet (P1), or when
    # the subject is uselessly short ("Fee from March", "Help").
    if signals.message and (not signals.intent or len(signals.subject.split()) < 4):
        used = len(" ".join(parts).split())
        parts.append(normalise(signals.message, max_words=max(20, max_words - used)))

    query = ". ".join(p for p in parts if p)
    return re.sub(r"\s+", " ", query).strip()


def from_ticket(ticket: dict, intent: str = "", entities: list[str] | None = None) -> str:
    """Convenience wrapper for a raw ticket dict from `synthetic_tickets.json`."""
    return build_query(
        QuerySignals(
            subject=ticket.get("subject", ""),
            message=ticket.get("message", ""),
            intent=intent,
            entities=entities or [],
            product_area=ticket.get("product_area", ""),
            category=ticket.get("category", ""),
        )
    )
