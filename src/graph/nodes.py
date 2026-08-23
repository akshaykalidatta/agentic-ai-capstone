"""
The twelve nodes.

Each node takes state and returns a **partial** dict. Each docstring starts with REAL, STUB or
PARTIAL, so you always know whether you are reading final logic or a placeholder. The rule for
what is already final: anything that is pure Python over inputs we already have.

Stub nodes read `state["stubs"]`, a per-ticket script used by the tests to drive branches
without a model. See `scripted_value`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.graph.graph_state import (
    GraphState,
    loop_count,
    loop_exhausted,
    review_payload,
    times_node_ran,
)
from src.logging.trace_logger import traced
from src.utils.config import app_config, routing_rules
from src.utils.constants import SAFETY_CRITICAL_CODES
from src.utils.schemas import (
    ClauseRef,
    PolicyAnalysis,
    Precondition,
    RetrievalAttempt,
    RetrievedChunk,
    ReviewerDecision,
    SafetyFlag,
    ValidationResult,
)

log = logging.getLogger(__name__)


class Passes(list):
    """
    Marks a stub value as one element per pass: `Passes([False, False, True])`.

    A distinct type rather than "any list means per-pass", because several stub values are
    legitimately lists -- `safety_flags=[{...}]` would otherwise hand back one dict.
    """


def scripted_value(state: GraphState, key: str, default: Any, pass_index: int = 0) -> Any:
    """Read a stub value. `Passes` is indexed by pass; anything else is returned as-is."""
    stubs = state.get("stubs") or {}
    if key not in stubs:
        return default
    value = stubs[key]
    if isinstance(value, Passes):
        return value[min(pass_index, len(value) - 1)] if value else default
    return value


def loop_caps() -> dict[str, int]:
    return app_config().get("graph", {}).get("loop_caps", {}) or {}


def rules() -> dict[str, Any]:
    return routing_rules()


# ================================================================================= 1. triage


@traced("triage")
def triage(state: GraphState) -> dict[str, Any]:
    """
    REAL. Two layers: deterministic patterns, then a `fast`-model pass that can only *add*
    flags. Classifies the message, never the request's merit -- six tickets are hostile with a
    completely legitimate request, and letting tone reach the route is the headline failure.

    Degrades to patterns alone if the model is unreachable, which still passes P2's gate.
    """
    from src.agents.triage import triage_ticket

    # Scripted flags still override, so the topology tests can drive the bypass without a model.
    scripted_flags = scripted_value(state, "safety_flags", None)
    if scripted_flags is not None:
        flags = [
            f if isinstance(f, SafetyFlag) else SafetyFlag.model_validate(f) for f in scripted_flags
        ]
        sentiment = scripted_value(state, "sentiment", "neutral")
        return {
            "sentiment": sentiment,
            "safety_flags": flags,
            "safety_critical": any(f.code in SAFETY_CRITICAL_CODES for f in flags),
            "intent": scripted_value(state, "intent", ""),
            "entities": scripted_value(state, "entities", {}),
            "notes": ["triage: scripted"],
            "_summary": f"scripted flags={','.join(f.code for f in flags) or 'none'}",
        }

    return triage_ticket(state["ticket"], use_model=not state.get("no_model", False))


# ============================================================================ 2. rule engine


@traced("preconditions")
def preconditions(state: GraphState) -> dict[str, Any]:
    """
    REAL. Eligibility computed from fields, handed to the model as fact it must not re-derive.

    A precondition that needs something only the prose has -- a fee date, a disputed amount --
    stays `met=None` until triage extracts it. `None` drives ASK_MORE_INFO; collapsing it to
    False would assert the opposite of what we know.
    """
    from src.routing.rules_engine import compute

    computed = compute(
        state["ticket"], state.get("entities", {}), state.get("customer_history", [])
    )
    determinate = sum(1 for p in computed.values() if p.met is not None)
    return {
        "preconditions": computed,
        "_summary": f"{len(computed)} preconditions, {determinate} determinate",
    }


# ============================================================================== 3. retrieval

# Building a Retriever loads a 130 MB model and opens Chroma. Module-level so it happens once
# per process, and imported inside the function so this module stays importable without torch.
_retriever_instance: Any = None


def get_retriever() -> Any:
    global _retriever_instance
    if _retriever_instance is None:
        from src.retrieval.retriever import build_default_retriever

        _retriever_instance = build_default_retriever()
    return _retriever_instance


def set_retriever(retriever: Any) -> None:
    """Injection point for tests and `--stub-retrieval`. Pass None to reset."""
    global _retriever_instance
    _retriever_instance = retriever


@traced("retrieve")
def retrieve(state: GraphState) -> dict[str, Any]:
    """
    REAL. All the retrieval policy -- over-fetch, similarity floor, dedupe, stitch, guaranteed
    context -- lives in `src/retrieval/retriever.py`, which is why this node is short.

    The attempt counter increments here, not in `refine_query`: this is the node that spends
    the budget, and it runs on the first pass too.
    """
    ticket = state["ticket"]
    attempt_number = loop_count(state, "retrieval_refine") + 1
    query = state.get("retrieval_query") or ""

    if not query:
        from src.retrieval.query_builder import QuerySignals, build_query

        # `entities` is a dict in state (the rule engine wants named fields) and a list of
        # terms in the query. Flattened here, at the seam, rather than compromising either.
        entities = state.get("entities", {}) or {}
        query = build_query(
            QuerySignals(
                subject=ticket.subject,
                message=ticket.message,
                intent=state.get("intent", "") or "",
                entities=[str(v) for v in entities.values() if v not in (None, "")],
                product_area=ticket.product_area,
                category=ticket.category,
            )
        )

    retriever = get_retriever()
    # The mode lives on the *store*, not the Retriever wrapper, so a bm25-only or stubbed run
    # is labelled honestly in the audit record instead of always reading "dense".
    mode = getattr(retriever, "mode", None) or getattr(
        getattr(retriever, "store", None), "mode", "dense"
    )
    result = retriever.retrieve(
        query,
        k=state.get("k_override") or None,
        sentiment=state.get("sentiment", "") or "",
        category=ticket.category,
        product_area=ticket.product_area,
    )
    chunks = [
        RetrievedChunk(
            chunk_id=hit.chunk_id,
            policy_id=hit.policy_id,
            source_file=hit.source_file,
            chunk_type=hit.chunk_type,
            title=hit.title,
            text=hit.text,
            similarity=hit.similarity,
            citable=hit.citable,
            injected=hit.injected,
        )
        for hit in result.hits
    ]

    return {
        "retrieval_query": query,
        "retrieval_mode": mode,
        "retrieved": chunks,
        "context_block": result.context_block(),
        "retrieval_attempts": attempt_number,
        "retrieval_log": [  # reducer key: the new attempt only, never the whole log
            RetrievalAttempt(
                attempt=attempt_number,
                query=query,
                mode=mode,
                top_similarity=round(float(result.top_similarity or 0.0), 4),
                policy_ids=result.policy_ids(),
                source_files=result.source_files(),
                below_floor=result.below_floor,
                scope_signal=result.scope_signal,
            )
        ],
        "_summary": (
            f"attempt {attempt_number}: {len(chunks)} chunks, top={result.top_similarity:.3f}, "
            f"ids={','.join(result.policy_ids()) or '-'}"
        ),
    }


@traced("refine_query")
def refine_query(state: GraphState) -> dict[str, Any]:
    """
    REAL. Loop 1's body.

    A refinement must change an input -- an identical retry returns identical results, burns a
    retrieval and advances a counter toward a cap. So this changes two, deterministically:
    it appends the missing facts analysis reported, and it widens k.
    """
    analysis = state.get("policy_analysis")
    base_query = state.get("retrieval_query", "") or ""
    extra_terms = " ".join((analysis.missing_facts if analysis else []) or [])
    widened_k = int(app_config()["retrieval"]["search"].get("k", 5)) * 2

    query = f"{base_query}. {extra_terms}".strip(". ").strip() if extra_terms else base_query
    return {
        "retrieval_query": query,
        "k_override": widened_k,
        "notes": [f"refine_query: k -> {widened_k}"],
        "_summary": f"k->{widened_k}" + (f" +{len(extra_terms.split())} words" if extra_terms else ""),
    }


# ============================================================================== 4. reasoning


def absence_detected(state: GraphState) -> tuple[bool, list[str]]:
    """
    Does "no policy covers this" hold? (`lld_notes.md` §3, corrected by measurement.)

    §3 guessed "two of three signals". Measured on the 107 golden tickets, the three are not
    equally good, so they are weighted rather than counted:

    | Signal | Measured | Weight |
    | --- | --- | --- |
    | A scope note out-ranked every clause | fires on 5/8 no-policy, **0/99 covered** | strong |
    | Top-1 below the similarity floor | fires on awkwardly-worded but covered tickets | weak |
    | Nothing citable was retrieved | almost never fires -- BM25 always returns something | weak |

    A signal with zero false positives across 99 tickets does not need corroboration, so the
    scope note is sufficient alone. The other two still need a partner, because escalating a
    covered ticket is the mirror-image error the eval tracks as `false_absence_rate`.

    Absence is only detectable at all because every document contributes a `scope` chunk saying
    what it does *not* cover. A mortgage-escrow question matches no clause, but it does match
    "does not cover mortgage or home equity escrow adjustments".
    """
    strong: list[str] = []
    weak: list[str] = []

    attempts = state.get("retrieval_log") or []
    if attempts:
        last = attempts[-1]
        if last.scope_signal:
            strong.append("a scope note out-ranked every clause")
        if last.below_floor:
            weak.append("top-1 below the similarity floor")

    # Guaranteed-context clauses excluded: CON-010/011 are in context on every ticket, so
    # counting them would mean absence could never be detected at all.
    earned = [
        c for c in (state.get("retrieved") or []) if c.citable and not c.injected and c.policy_id
    ]
    if not earned:
        weak.append("no citable clause was retrieved")

    fired = strong + weak
    return (bool(strong) or len(weak) >= 2), fired


@traced("analyse_policy")
def analyse_policy(state: GraphState) -> dict[str, Any]:
    """
    STUB -- P3 replaces the body with a structured `reason`-model call.

    The proxy for "verified" is "at least one citable, non-injected clause came back". That is
    deliberately weak: a clause can be retrieved without deciding the question, which is the
    distinction the real node exists to draw. Expect P3 to score *worse* than this stub before
    it scores better.

    `injected=False` matters -- CON-010/011 are in context on every ticket, so counting them
    would mark all 150 verified, including the 8 with no supporting policy at all.
    """
    pass_index = times_node_ran(state, "analyse_policy")
    retrieved = state.get("retrieved", []) or []

    if state.get("no_model") or "policy_verified" in (state.get("stubs") or {}):
        earned = [c for c in retrieved if c.citable and not c.injected and c.policy_id]
        # Absence detection, not just "did anything come back". Without it the deterministic
        # path marks all 8 no-policy tickets verified, because BM25 always returns *something*.
        absent, _ = absence_detected(state)
        default_verified = bool(earned) and not absent
        verified = bool(scripted_value(state, "policy_verified", default_verified, pass_index))
        missing = list(scripted_value(state, "missing_facts", [], pass_index))
        analysis = PolicyAnalysis(
            deciding_clauses=(
                [ClauseRef(policy_id=earned[0].policy_id, why="scripted")]
                if verified and earned
                else []
            ),
            missing_facts=missing,
            policy_verified=verified,
            self_certainty=float(scripted_value(state, "self_certainty", 0.5, pass_index)),
        )
        return {
            "policy_analysis": analysis,
            "_summary": f"scripted verified={verified} missing={len(missing)}",
        }

    from src.agents.policy import analyse

    # A retry must change an input. On a reconsider pass the disagreement is stated
    # explicitly, so the second call is a different question rather than a wasted one.
    disagreement = ""
    if pass_index and state.get("rule_route") != state.get("llm_route"):
        disagreement = (
            f"On the previous pass the deterministic rules concluded "
            f"{state.get('rule_route')} and the model concluded {state.get('llm_route')}. "
            f"Look again at which clause actually decides this."
        )

    from src.routing.thread_pressure import assess, context_block

    history = state.get("customer_history", []) or []
    analysis = analyse(
        state["ticket"],
        retrieved,
        state.get("preconditions", {}),
        disagreement_note=disagreement,
        history_block=context_block(history, assess(state["ticket"], history)),
    )

    # Two absence signals overrule a model that claims to have verified something. The model
    # sees the clauses in its context and is inclined to find one relevant; the signals are
    # measured outside it, which is exactly why they can outvote it.
    absent, fired = absence_detected(state)
    notes: list[str] = []
    if analysis.policy_verified and absent:
        analysis = analysis.model_copy(update={"policy_verified": False, "deciding_clauses": []})
        notes.append(f"absence detected: {'; '.join(fired)}")

    return {
        "notes": notes,
        "policy_analysis": analysis,
        "_summary": (
            f"verified={analysis.policy_verified} "
            f"deciding={','.join(analysis.deciding_ids()) or '-'} "
            f"missing={len(analysis.missing_facts)}"
        ),
    }


# ================================================================================ 5. routing


@traced("route_decision")
def route_decision(state: GraphState) -> dict[str, Any]:
    """
    REAL. Two independent proposals, reconciled (HLD D4).

    The rule engine proposes from fields; the model proposes from clauses. The model is NOT
    shown the rule engine's answer -- telling it would turn a second opinion into agreement
    and destroy the disagreement signal, which is the whole point.

    Ladder order is load-bearing. The two rules-win cases are exactly where a persuasive
    message is most likely to talk a model out of the right answer, so they resolve before the
    model's opinion is consulted at all.
    """
    from src.routing.rules_engine import propose_route as rules_propose
    from src.routing.target_map import resolve_target

    ticket = state["ticket"]
    flags = state.get("safety_flags", []) or []
    critical = [f for f in flags if f.code in SAFETY_CRITICAL_CODES]
    analysis = state.get("policy_analysis") or PolicyAnalysis()
    verified = bool(analysis.policy_verified)
    pass_index = times_node_ran(state, "route_decision")
    scripted = state.get("stubs") or {}

    if "rule_route" in scripted:
        rule_route, rule_reason = scripted_value(state, "rule_route", None, pass_index), "scripted"
    else:
        rule_route, rule_reason = rules_propose(ticket, state.get("preconditions", {}), flags)

    if "llm_route" in scripted or state.get("no_model"):
        llm_route = scripted_value(state, "llm_route", None, pass_index)
        llm_reason, llm_target = "scripted", None
    elif critical:
        # The bypass already owns this ticket; spending a reasoning call on it is waste.
        llm_route, llm_reason, llm_target = None, "not consulted (safety bypass)", None
    else:
        from src.agents.policy import propose_route as model_propose

        llm_route, llm_reason, llm_target = model_propose(
            ticket, analysis, state.get("preconditions", {}), state.get("retrieved", []) or []
        )

    if critical:
        route = "ESCALATE"
        rationale = f"safety-critical flag {critical[0].code}: rules win outright"
    elif not verified:
        route = "ESCALATE"
        rationale = "policy could not be verified: rules win outright"
    elif rule_route is None and llm_route is None:
        # Neither half had an opinion. That is not agreement -- `None == None` is the trap --
        # and a ticket nobody can route is precisely what a human is for.
        route = "ESCALATE"
        rationale = "no rule fired and no model proposal available"
    elif rule_route == llm_route:
        route, rationale = llm_route, f"rules and model agree: {llm_reason}"
    elif rule_route is None:
        route, rationale = llm_route, f"no rule covers this ticket; model: {llm_reason}"
    elif llm_route is None:
        route, rationale = rule_route, f"model gave no usable proposal; rules: {rule_reason}"
    else:
        # A disagreement is a signal to look again, not a verdict. ESCALATE is the safe
        # holding position while the confidence loop decides; finalising here would skip the
        # loop entirely and throw D4's benefit away.
        route = "ESCALATE"
        rationale = f"route disagreement (rules={rule_route}: {rule_reason} | model={llm_route})"

    target, visible = resolve_target(
        route=route,
        safety_flags=flags,
        rule_reason=rule_reason,
        category=ticket.category,
        product_area=ticket.product_area,
        no_policy_found=not verified,
    )
    if route == "ESCALATE":
        from src.routing.thread_pressure import assess, escalation_target_for

        history = state.get("customer_history", []) or []
        target = escalation_target_for(assess(ticket, history), target)
    # The model may name a queue the rules did not know about (an estate, a mortgage). Accept
    # it only when nothing more authoritative fired.
    if target is None and llm_target and route in {"ESCALATE", "REFUSE"}:
        target = llm_target

    update: dict[str, Any] = {
        "rule_route": rule_route,
        "llm_route": llm_route,
        "route": route,
        "escalation_target": target,
        "escalation_visible_to_customer": visible,
        "route_rationale": rationale,
        "_summary": f"rules={rule_route} model={llm_route} -> {route} | {target or '-'}",
    }

    # Loop 1 lands here when it runs out of budget. Routers cannot write, so recording the cap
    # is this node's job. The `not in` guard matters because the confidence loop re-enters
    # this node and `loops_capped` concatenates.
    already = state.get("loops_capped") or []
    if (
        not verified
        and loop_exhausted(state, "retrieval_refine", loop_caps())
        and "retrieval_refine" not in already
    ):
        update["loops_capped"] = ["retrieval_refine"]
    return update


@traced("score_confidence")
def score_confidence(state: GraphState) -> dict[str, Any]:
    """
    STUB score, REAL cap handling. P5 fits the real weights.

    Two things here are final. The forcing lives in this node because a router can only pick a
    string -- routers choose, nodes write. And a capped loop resolves **upward**: missing facts
    give ASK_MORE_INFO, otherwise ESCALATE. Never relax toward AUTO_RESOLVE.
    """
    from src.routing.confidence import compose

    pass_index = times_node_ran(state, "score_confidence")
    if "confidence" in (state.get("stubs") or {}):
        confidence = float(scripted_value(state, "confidence", 0.85, pass_index))
        components = {"scripted": confidence}
    else:
        confidence, components = compose(
            chunks=state.get("retrieved", []) or [],
            analysis=state.get("policy_analysis") or PolicyAnalysis(),
            preconditions=state.get("preconditions", {}),
            rule_route=state.get("rule_route"),
            llm_route=state.get("llm_route"),
        )
    route = state.get("route", "ESCALATE")
    floor = float((rules().get("route_confidence_floors", {}) or {}).get(route, 0.5))
    below_floor = confidence < floor

    # Count this pass BEFORE testing the cap. The other order makes the counter read 2 by the
    # time the router looks, so the router stops looping but this node never forces -- the loop
    # appears to work and does nothing.
    passes_used = pass_index + 1
    cap = int(loop_caps().get("confidence_recheck", 2))

    update: dict[str, Any] = {
        "confidence": confidence,
        "confidence_parts": components,
        "recheck_attempts": passes_used,
    }

    if below_floor and passes_used >= cap:
        analysis = state.get("policy_analysis") or PolicyAnalysis()
        forced_route = "ASK_MORE_INFO" if analysis.missing_facts else "ESCALATE"
        update.update(
            route=forced_route,
            route_rationale=(
                f"confidence {confidence:.2f} below {route} floor {floor:.2f} after "
                f"{passes_used} passes -> forced {forced_route}"
            ),
            loops_capped=["confidence_recheck"],
        )
        update["_summary"] = f"{confidence:.2f} < {floor:.2f}, capped -> {forced_route}"
        return update

    update["_summary"] = (
        f"{confidence:.2f} vs {route} floor {floor:.2f} "
        f"-> {'recheck' if below_floor else 'ok'} (pass {passes_used}/{cap})"
    )
    return update


# =============================================================================== 6. drafting

STUB_DRAFT_BY_ROUTE: dict[str, str] = {
    "AUTO_RESOLVE": "[STUB draft] Resolution offered under the deciding clause.",
    "ESCALATE": "[STUB draft] Acknowledgement; the case has been routed to a specialist.",
    "REFUSE": "[STUB draft] Decline the framing, offer the legitimate path.",
    "ASK_MORE_INFO": "[STUB draft] Request the specific missing facts, nothing already supplied.",
}

BARE_ACKNOWLEDGEMENT = (
    "Thank you for getting in touch. We are looking into this and a specialist will follow up "
    "with you shortly."
)

# Used when no clause covers the request. The golden set scores the 8 no-policy tickets on the
# route AND the wording -- escalating without saying why tells the customer nothing.
UNVERIFIED_POLICY_ACKNOWLEDGEMENT = (
    "Thank you for getting in touch. We could not verify a policy that covers this request, so "
    "it is going to a specialist team to confirm the position. They will follow up with you."
)

# Fixed text, no model call, no policy in context. The abusive-content policy requires a short
# human reply for a crisis disclosure and forbids pairing one with a policy quote; the surest
# way to honour that is to have nothing to quote and no model in the loop.
SAFETY_BYPASS_DRAFT = (
    "Thank you for telling us. A member of our team will contact you directly and shortly. "
    "We are not able to resolve this over this channel, and we want to make sure you speak "
    "with someone who can help."
)


@traced("draft_reply")
def draft_reply(state: GraphState) -> dict[str, Any]:
    """
    REAL. The route is an *input* here.

    Drafting before routing makes the draft the evidence for the route -- the model writes
    something helpful, reads its own prose, and concludes AUTO_RESOLVE because the answer
    sounds resolved. On the 45 hard tickets that failure is near-total.

    If drafting fails outright, the ticket escalates with a bare acknowledgement rather than
    shipping a guess.
    """
    route = state.get("route", "ESCALATE")
    retrieved = state.get("retrieved", []) or []
    attempt = loop_count(state, "draft_repair") + 1

    if state.get("no_model") or "draft" in (state.get("stubs") or {}):
        analysis = state.get("policy_analysis") or PolicyAnalysis()
        body = scripted_value(state, "draft", STUB_DRAFT_BY_ROUTE.get(route, "[STUB draft]"))
        cited = [c.policy_id for c in retrieved if c.citable and c.policy_id and not c.injected]
        if not analysis.policy_verified:
            body, cited = UNVERIFIED_POLICY_ACKNOWLEDGEMENT, []
        elif state.get("loops_capped"):
            body, cited = BARE_ACKNOWLEDGEMENT, []
        return {
            "draft": body,
            "cited_policy_ids": cited,
            "draft_attempts": attempt,
            "_summary": f"scripted route={route}",
        }

    from src.agents.response import draft as write_draft

    validation = state.get("validation")
    repair_note = ""
    if validation is not None and not validation.ok:
        # A repair must change an input, so the specific violation is named rather than
        # re-sending the identical prompt and hoping.
        problems = (
            [f"you cited {pid}, which was never retrieved" for pid in validation.hallucinated_citations]
            + [f"you cited {pid}, which is internal-only" for pid in validation.uncitable_citations]
            + list(validation.violations)
        )
        repair_note = "; ".join(problems)

    reviewer = state.get("reviewer")
    try:
        body, cited = write_draft(
            state["ticket"],
            route,
            retrieved,
            state.get("policy_analysis") or PolicyAnalysis(),
            sentiment=state.get("sentiment", "neutral"),
            escalation_visible=bool(state.get("escalation_visible_to_customer", True)),
            reviewer_comment=(reviewer.comments if reviewer and reviewer.action ==
                              "REQUEST_REGENERATION" else ""),
            repair_note=repair_note,
        )
    except Exception as exc:
        log.warning("drafting failed for %s (%s); escalating", state.get("ticket_id"), exc)
        analysis = state.get("policy_analysis") or PolicyAnalysis()
        fallback = (
            BARE_ACKNOWLEDGEMENT if analysis.policy_verified else UNVERIFIED_POLICY_ACKNOWLEDGEMENT
        )
        return {
            "draft": fallback,
            "cited_policy_ids": [],
            "draft_attempts": attempt,
            "route": "ESCALATE",
            "route_rationale": f"drafting unavailable ({exc})",
            "notes": [f"draft_reply: degraded, {exc}"],
            "_summary": "drafting failed -> bare acknowledgement, ESCALATE",
        }

    return {
        "draft": body,
        "cited_policy_ids": cited,
        "draft_attempts": attempt,
        "_summary": f"route={route} {len(body)} chars cites={','.join(cited) or '-'}",
    }


@traced("validate_draft")
def validate_draft(state: GraphState) -> dict[str, Any]:
    """
    REAL citation check, STUB content scan.

    The citation half is mechanical -- a cited ID is in the retrieved set or it is not -- which
    is why P4's gate can be zero rather than a percentage. The content scan needs a judge
    ("promises a specific resolution date" is not a regex) and waits for P8.
    """
    cited = list(state.get("cited_policy_ids", []) or [])
    retrieved = state.get("retrieved", []) or []
    available_ids = {c.policy_id for c in retrieved if c.policy_id}
    uncitable_ids = {c.policy_id for c in retrieved if c.policy_id and not c.citable}
    uncitable_ids |= set(rules().get("non_citable_policy_ids", []) or [])

    hallucinated = [pid for pid in cited if pid not in available_ids]
    quoted_internal = [pid for pid in cited if pid in uncitable_ids]
    from src.agents.response import scan_draft

    violations = list(
        scripted_value(state, "violations", [], loop_count(state, "draft_repair") - 1)
    )
    violations += scan_draft(state.get("draft", "") or "")

    # A silent referral that the draft mentions is the one failure the customer must never
    # see: naming a Conduct Review referral warns the person the account holder may need
    # protecting from (TCK-1078).
    if not state.get("escalation_visible_to_customer", True):
        target = (state.get("escalation_target") or "").lower()
        body_lower = (state.get("draft") or "").lower()
        if target and target in body_lower:
            violations.append(f"names a referral that must stay invisible ({target})")

    result = ValidationResult(
        ok=not (hallucinated or quoted_internal or violations),
        violations=violations,
        hallucinated_citations=hallucinated,
        uncitable_citations=quoted_internal,
    )

    update: dict[str, Any] = {
        "validation": result,
        "notes": ["validate_draft: citation check REAL, content scan STUB (P4/P8)"],
        "_summary": (
            "ok" if result.ok else f"halluc={hallucinated} internal={quoted_internal}"
        ),
    }

    if not result.ok and loop_exhausted(state, "draft_repair", loop_caps()):
        update.update(
            route="ESCALATE",
            route_rationale=(
                f"draft failed validation after {loop_count(state, 'draft_repair')} attempts"
            ),
            draft=BARE_ACKNOWLEDGEMENT,
            cited_policy_ids=[],
            loops_capped=["draft_repair"],
        )
        update["_summary"] += " | capped -> ESCALATE"
    return update


# =========================================================================== safety bypass


@traced("safety_escalate")
def safety_escalate(state: GraphState) -> dict[str, Any]:
    """
    REAL structure, STUB wording.

    The return value is the point: `retrieved=[]`, `context_block=""`. Not skipped for speed --
    the context has to be *provably* empty in the audit record, because a self-harm disclosure
    flowing through the normal path gets drafted with fee clauses sitting in context:
    "I'm sorry to hear that. Regarding your $35 overdraft fee, under FEE-001...".

    Route is ESCALATE, never REFUSE. A person disclosing a crisis is not a policy violation.
    """
    critical_flags = [
        f for f in (state.get("safety_flags") or []) if f.code in SAFETY_CRITICAL_CODES
    ]
    code = critical_flags[0].code if critical_flags else "CRISIS_OTHER"
    targets_by_safety_code = rules().get("safety_escalation_targets", {}) or {}
    silent_codes = set(rules().get("silent_escalation_codes", []) or [])
    target = targets_by_safety_code.get(code, "Threat Response")

    return {
        "route": "ESCALATE",
        "escalation_target": target,
        # False for suspected financial abuse: telling the customer we referred it warns
        # exactly the person who may be exploiting them.
        "escalation_visible_to_customer": code not in silent_codes,
        "route_rationale": f"safety bypass: {code} (no KB text in context)",
        "rule_route": "ESCALATE",
        "llm_route": None,
        "retrieved": [],
        "context_block": "",
        "retrieval_mode": "bypassed",
        "confidence": 1.0,
        "confidence_parts": {"safety_override": 1.0},
        "draft": SAFETY_BYPASS_DRAFT,
        "cited_policy_ids": [],
        "validation": ValidationResult(ok=True),
        "notes": [f"safety_escalate: bypass taken on {code}"],
        "_summary": f"{code} -> {target} (visible={code not in silent_codes})",
    }


# ================================================================================ 7. review


@traced("hitl_gate")
def hitl_gate(state: GraphState) -> dict[str, Any]:
    """
    REAL for all three modes.

    Every path passes through here, including the safety bypass -- nothing reaches a customer
    under any configuration. The three modes are architectural: without `auto` and `simulate`,
    a human gate in front of 150 tickets means no metric is ever produced; without
    `interactive`, the gate is a notification.

    `interactive` suspends the graph with `interrupt()` and never falls back to `auto`, so
    nobody can publish an "interactive" number no human ever saw. `auto` and `simulate` are
    ordinary nodes and must not call `interrupt()` -- one that did would hang every eval run
    waiting for a person who is not there.

    **On resume LangGraph re-executes this node from the top.** Everything above the
    `interrupt()` call therefore happens twice and has to stay pure: `review_payload` only
    reads state, and every write in this function is below the line.
    """
    mode = state.get("hitl_mode", "auto")
    escalation_target = state.get("escalation_target")
    edited_draft: str | None = None
    override_target: str | None = None
    reviewer_name = f"{mode}-mode"

    if mode == "interactive":
        from langgraph.types import interrupt

        # Raises the first time through, suspending the graph with this payload attached to the
        # checkpoint. `Command(resume=...)` re-enters the node and this returns that value.
        submitted = interrupt(review_payload(state)) or {}
        action = str(submitted.get("action") or "APPROVE")
        reason = str(submitted.get("comments") or "")
        reviewer_name = str(submitted.get("reviewer") or "reviewer")
        edited_draft = submitted.get("edited_draft") or None
        override_target = submitted.get("escalation_target") or None
    elif mode == "simulate":
        golden = state.get("golden")
        if golden is None:
            # 43 tickets have no golden record. Falling back is right; hiding it is not.
            action, reason = "APPROVE", "no golden record; fell back to auto-approve"
        else:
            action, reason = golden.expected_reviewer_action, "replayed from golden set"
    else:
        action = "APPROVE_AND_ROUTE" if escalation_target else "APPROVE"
        reason = "auto mode"

    decision = ReviewerDecision(
        action=action,
        comments=reason,
        # Kept alongside the original rather than replacing `state["draft"]`. Edit size is a
        # quality signal you cannot compute once you have overwritten what you would measure
        # against, and nothing is ever sent, so there is no "final" copy to keep authoritative.
        edited_draft=edited_draft,
        reviewed_at=datetime.now(timezone.utc),
        reviewer=reviewer_name,
        mode=mode,
    )
    update: dict[str, Any] = {
        "reviewer": decision,
        "notes": [f"hitl_gate: {mode} -> {action}"],
        "_summary": f"{mode}: {action} (target={escalation_target or '-'})",
    }

    if action == "ESCALATE_OVERRIDE":
        # The agent's route is left standing. The audit record answers "what did the agent
        # decide", and rewriting it here would quietly move every overridden ticket out of the
        # route-accuracy denominator. The override is recorded in `outputs/reviews.jsonl`.
        update["notes"].append(
            f"hitl_gate: reviewer overrode {state.get('route')} -> ESCALATE"
            f" ({override_target or escalation_target or 'no queue named'})"
        )

    if action == "REQUEST_REGENERATION":
        # Routers choose, nodes write: `after_review` reads this counter to stop a reviewer
        # cycling one draft forever, but only this node may increment it.
        attempts = loop_count(state, "review_regeneration") + 1
        update["regeneration_attempts"] = attempts
        capped = int(loop_caps().get("review_regeneration", 3))
        if attempts >= capped and "review_regeneration" not in (state.get("loops_capped") or []):
            # `not in` guard: `loops_capped` concatenates, and this node is re-entered by its
            # own loop.
            update["loops_capped"] = ["review_regeneration"]
    return update


# ================================================================================= 8. audit

# One logger per run, so 150 tickets append to one file instead of opening 150 handles.
_audit_loggers: dict[str, Any] = {}


def set_audit_logger(run_id: str, logger: Any) -> None:
    _audit_loggers[run_id] = logger


@traced("audit_log")
def audit_log(state: GraphState) -> dict[str, Any]:
    """
    REAL. Writes the append-only record, then the case-history entry.

    That order matters: if the thread-store write fails you still have a complete record of the
    decision. Reversed, a crash between the two leaves the next ticket in the thread reading
    history for a decision that was never recorded.
    """
    from src.logging.audit_logger import AuditLogger
    from src.memory.customer_thread_store import CustomerThreadStore

    run_id = state.get("run_id", "adhoc")
    logger = _audit_loggers.get(run_id)
    if logger is None:
        logger = AuditLogger(run_id)
        _audit_loggers[run_id] = logger

    record = logger.write(state)
    CustomerThreadStore.default().append_from_state(state)

    return {
        "finished_at": datetime.now(timezone.utc),
        "notes": [f"audit_log: wrote {logger.path.name}"],
        "_summary": f"route={record['route']} -> {logger.path.name}",
    }


# Keys must match `constants.NODE_NAMES`; `tests/test_graph_topology.py` asserts that.
NODES: dict[str, Any] = {
    "triage": triage,
    "preconditions": preconditions,
    "retrieve": retrieve,
    "refine_query": refine_query,
    "analyse_policy": analyse_policy,
    "route_decision": route_decision,
    "score_confidence": score_confidence,
    "draft_reply": draft_reply,
    "validate_draft": validate_draft,
    "safety_escalate": safety_escalate,
    "hitl_gate": hitl_gate,
    "audit_log": audit_log,
}
