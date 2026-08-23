"""
Composed confidence (HLD D3).

Asking a model for its own confidence gives roughly the same high number for everything, and a
number that never dips cannot drive a loop. So confidence is composed from signals that are
observable *outside* the model, with the model's own opinion capped at a 10% minority share:

    0.30  retrieval_strength        did we find anything, and how well
    0.25  clause_coverage           does a clause actually DECIDE this, or merely touch it
    0.20  precondition_determinacy  were the facts we needed present and unambiguous
    0.15  route_agreement           do the rule engine and the model agree
    0.10  self_certainty            the model's own number

Weights are provisional and get fitted against the 107 golden confidence bands in P5. What is
already settled is the *shape*: every component is independently measurable, and none of them
can be talked up by a persuasive ticket.

The bands the dataset implies, and the reason ASK_MORE_INFO's floor is low:

| Route | Band |
| --- | --- |
| AUTO_RESOLVE | 0.80 - 1.00 |
| REFUSE | 0.75 - 1.00 |
| ESCALATE | 0.55 - 0.95 |
| ASK_MORE_INFO | **0.30 - 0.70** |

Low confidence is a legitimate terminal state, not something to iterate away.
"""

from __future__ import annotations

from src.utils.config import routing_rules
from src.utils.schemas import PolicyAnalysis, Precondition, RetrievedChunk

DEFAULT_WEIGHTS: dict[str, float] = {
    "retrieval_strength": 0.30,
    "clause_coverage": 0.25,
    "precondition_determinacy": 0.20,
    "route_agreement": 0.15,
    "self_certainty": 0.10,
}


def weights() -> dict[str, float]:
    configured = (routing_rules().get("confidence_weights") or {}) or DEFAULT_WEIGHTS
    total = sum(configured.values()) or 1.0
    # Normalise, so editing one weight in YAML without rebalancing the rest cannot silently
    # push every score above 1.0.
    return {name: value / total for name, value in configured.items()}


def retrieval_strength(chunks: list[RetrievedChunk]) -> float:
    """
    Top dense similarity, rescaled, and zero if nothing earned its place.

    Injected clauses are excluded: CON-010/011 are in context on every ticket, so counting
    them would give a floor of "we retrieved something" to the eight tickets whose true answer
    is that no policy covers them.

    The 0.30-0.75 window is the observed useful range for bge-small on this corpus -- 0.30 is
    near the noise floor and anything above 0.75 is a near-verbatim match. Mapping that window
    onto 0..1 stops every ticket scoring a flat 0.5.
    """
    earned = [c for c in chunks if not c.injected and c.similarity is not None]
    if not earned:
        # Hybrid can return lexical-only hits with no cosine. They are real evidence, but
        # weaker than a dense match, so they score a fixed middling value rather than zero.
        lexical = [c for c in chunks if not c.injected and c.policy_id]
        return 0.45 if lexical else 0.0
    top = max(c.similarity or 0.0 for c in earned)
    return round(min(1.0, max(0.0, (top - 0.30) / 0.45)), 4)


def clause_coverage(analysis: PolicyAnalysis) -> float:
    """
    Does a clause *decide* the question: fully 1.0, partially 0.5, not at all 0.0.

    "Partially" is the case where policy was verified but only constraining clauses came
    back -- we know what we must not say, and not what we should do. That is a genuinely
    intermediate state and collapsing it either way loses the distinction.
    """
    if analysis.deciding_clauses:
        return 1.0
    if analysis.policy_verified or analysis.constraining_clauses:
        return 0.5
    return 0.0


def precondition_determinacy(preconditions: dict[str, Precondition]) -> float:
    """
    Fraction of preconditions that resolved either way.

    No preconditions at all scores 0.5, not 0.0: a digital-access ticket has no fee thresholds
    to evaluate, and penalising it for that would mean confidence tracked category rather than
    certainty.
    """
    if not preconditions:
        return 0.5
    determinate = sum(1 for p in preconditions.values() if p.met is not None)
    return round(determinate / len(preconditions), 4)


def route_agreement(rule_route: str | None, llm_route: str | None) -> float:
    """
    1.0 agree, 0.0 disagree, 0.5 when no rule fired.

    The middle value matters. `rule_route is None` means no rule covered the ticket, which is
    not the same as the rules contradicting the model -- scoring it 0.0 would punish every
    ticket outside the rule engine's coverage.
    """
    if rule_route is None or llm_route is None:
        return 0.5
    return 1.0 if rule_route == llm_route else 0.0


def compose(
    *,
    chunks: list[RetrievedChunk],
    analysis: PolicyAnalysis,
    preconditions: dict[str, Precondition],
    rule_route: str | None,
    llm_route: str | None,
) -> tuple[float, dict[str, float]]:
    """Returns `(confidence, components)`. Components are stored for P5 calibration."""
    components = {
        "retrieval_strength": retrieval_strength(chunks),
        "clause_coverage": clause_coverage(analysis),
        "precondition_determinacy": precondition_determinacy(preconditions),
        "route_agreement": route_agreement(rule_route, llm_route),
        "self_certainty": max(0.0, min(1.0, analysis.self_certainty)),
    }
    active = weights()
    score = sum(active.get(name, 0.0) * value for name, value in components.items())
    return round(min(1.0, max(0.0, score)), 4), components


def in_expected_band(route: str, confidence: float) -> bool:
    """Is this score inside the band the golden set expects for this route? P5's gate."""
    bands = routing_rules().get("route_confidence_bands", {}) or {}
    band = bands.get(route)
    if not band:
        return True
    return float(band[0]) <= confidence <= float(band[1])
