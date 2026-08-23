"""
The human review surface. Rendering only -- every decision lives in `src/hitl/review_service`.

    streamlit run app/streamlit_app.py

Streamlit re-executes this whole file on every widget interaction, which is why there is no
logic here to run an unpredictable number of times, why the compiled graph is behind
`@st.cache_resource`, and why every widget carries an explicit ticket-scoped key.

The review screen puts the retrieved clauses beside the draft. That adjacency is HLD §7's
load-bearing decision, not a layout preference: a reviewer shown only the draft is judging
fluency, and one who can see what the agent read is judging groundedness.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# `streamlit run` executes this file as a script, so the repo root is not on sys.path and
# `import src...` fails with a bare ModuleNotFoundError that says nothing about why.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.hitl.review_service import (  # noqa: E402  -- must follow the sys.path line
    InteractiveReviewUnavailable,
    ReviewService,
    action_choices,
    checkpointer_kind,
    confidence_calibration,
    evaluator_rows,
    filter_pending,
    pending_summary_rows,
    sample_tickets,
    split_by_agreement,
)
from src.hitl.reviewer_actions import ACTIONS

st.set_page_config(page_title="Northgate — human review", layout="wide")


@st.cache_resource
def service() -> ReviewService:
    """
    `cache_resource`, never `cache_data`: the service owns a compiled graph and a live sqlite
    connection, and `cache_data` tries to hash and copy what it caches.
    """
    return ReviewService()


def widget_key(name: str, thread_id: str) -> str:
    """
    Ticket-scoped and stable.

    Auto-generated keys collide across reruns, and the visible symptom is a text area that
    shows the previous ticket's draft and refuses to clear.
    """
    return f"{name}::{thread_id}"


# ---------------------------------------------------------------------------- review screen


def render_evidence_column(payload: dict) -> None:
    """Left column: what the agent read."""
    st.subheader("What the agent read")

    mode = payload.get("retrieval_mode")
    chunks = payload.get("retrieved") or []
    if mode == "bypassed":
        st.info(
            "**No knowledge-base text was retrieved, by design.** This ticket took the safety "
            "bypass, so the context window was provably empty when the reply was written. An "
            "empty panel here is the branch working."
        )
    elif not chunks:
        st.warning(f"Nothing retrieved (mode: {mode or 'unknown'}).")

    for chunk in chunks:
        citable = bool(chunk.get("citable", True))
        header = f"`{chunk.get('policy_id') or chunk.get('chunk_id')}` — {chunk.get('title') or ''}"
        if not citable:
            header = f"🔒 INTERNAL — {header}"
        with st.expander(header, expanded=citable):
            if not citable:
                st.error(
                    "Internal-only. Quoting this to a customer is both a citation error and a "
                    "strange reply — it is a drafting standard written for staff."
                )
            if chunk.get("injected"):
                st.caption("Injected as guaranteed context, not retrieved.")
            similarity = chunk.get("similarity")
            st.caption(
                f"{chunk.get('source_file') or '?'} · {chunk.get('chunk_type') or '?'}"
                + (f" · similarity {float(similarity):.3f}" if similarity is not None else "")
            )
            st.write(chunk.get("text") or "")

    with st.expander("Retrieval attempts", expanded=False):
        for attempt in payload.get("retrieval_log") or []:
            st.markdown(
                f"**attempt {attempt.get('attempt')}** · mode {attempt.get('mode')} · "
                f"top similarity {attempt.get('top_similarity')} · "
                f"below floor {attempt.get('below_floor')} · scope signal "
                f"{attempt.get('scope_signal')}"
            )
            st.code(attempt.get("query") or "", language=None)

    st.subheader("The ticket")
    ticket = payload.get("ticket") or {}
    st.markdown(f"**{ticket.get('subject')}**")
    st.caption(
        f"{ticket.get('category')} / {ticket.get('product_area')} · priority "
        f"{ticket.get('priority')} · {ticket.get('channel')} · {ticket.get('created_at')}"
    )
    for turn in payload.get("conversation") or []:
        role = turn.get("role")
        if role == "system":
            # A `system` turn is an internal event, not customer speech. A reviewer skimming
            # reads "Source IP geolocation: inconsistent" as something the customer wrote.
            st.warning(f"⚙ INTERNAL EVENT (not the customer) · {turn.get('text')}")
        else:
            st.markdown(f"**{role}** · {turn.get('timestamp')}")
            st.write(turn.get("text"))
    st.markdown("**customer (this message)**")
    st.write(ticket.get("message") or "")


def render_decision_column(payload: dict, thread_id: str) -> None:
    """Right column: what the agent decided and wrote."""
    st.subheader("What the agent decided")

    if not payload.get("escalation_visible_to_customer", True):
        # Unmissable, not a field among fields. TCK-1078: naming a Conduct Review referral in
        # the reply warns exactly the person the account holder may need protecting from.
        st.error(
            f"### 🔇 SILENT REFERRAL — {payload.get('escalation_target') or 'internal queue'}\n"
            "This case is being referred internally and **the reply must not mention it**. "
            "Check the draft below says nothing about the referral before you approve."
        )

    left, right = st.columns(2)
    left.metric("Route", str(payload.get("route")))
    right.metric("Confidence", f"{float(payload.get('confidence') or 0.0):.3f}")
    st.caption(f"Target: {payload.get('escalation_target') or '—'}")
    st.caption(payload.get("route_rationale") or "")

    rule_route, llm_route = payload.get("rule_route"), payload.get("llm_route")
    if payload.get("proposals_disagree"):
        st.error(
            f"**The two halves disagree.** Rules proposed `{rule_route}`, the model proposed "
            f"`{llm_route}`. Disagreement is this design's hard-case detector — it is the "
            "single most useful thing on this screen."
        )
    else:
        st.caption(f"rules proposed `{rule_route}` · model proposed `{llm_route}`")

    with st.expander("Confidence components", expanded=False):
        st.json(payload.get("confidence_parts") or {})

    st.markdown("**Computed facts** — the verdict *and* what it was computed from")
    for name, precondition in (payload.get("preconditions") or {}).items():
        verdict = {True: "✅", False: "❌", None: "❔"}[precondition.get("met")]
        st.markdown(f"{verdict} **{name}** — {precondition.get('reason') or ''}")
        st.caption(f"from {precondition.get('inputs')}")

    flags = payload.get("safety_flags") or []
    if flags:
        st.markdown("**Safety flags**")
        for flag in flags:
            st.markdown(
                f"🚩 `{flag.get('code')}` · {flag.get('severity')} · detector "
                f"`{flag.get('detector')}`"
            )
            st.caption(flag.get("evidence_span") or "(no span recorded)")

    loops = payload.get("loops") or {}
    capped = payload.get("loops_capped") or []
    st.caption(f"loops {loops}" + (f" · **CAPPED: {', '.join(capped)}**" if capped else ""))

    history = payload.get("customer_history") or []
    if history:
        pressure = payload.get("thread_pressure") or {}
        st.markdown(
            f"**This customer has written before** — thread pressure level "
            f"{pressure.get('level')}: {pressure.get('reason')}"
        )
        for entry in history:
            st.caption(
                f"{str(entry.get('created_at'))[:10]} {entry.get('ticket_id')}: "
                f"{entry.get('subject')} → {entry.get('disposition')}"
            )

    st.subheader("The draft")
    st.caption(f"cites: {', '.join(payload.get('cited_policy_ids') or []) or '—'}")
    validation = payload.get("validation") or {}
    if not validation.get("ok", True):
        st.warning(f"Validation did not pass: {validation}")

    render_actions(payload, thread_id)


def render_actions(payload: dict, thread_id: str) -> None:
    """The six actions. The service decides what each one does; this only collects it."""
    review = service()
    allowed = review.regeneration_allowed(payload)
    choices = action_choices(payload, regeneration_allowed=allowed)

    edited = st.text_area(
        "Reply (edit it here to record an EDIT)",
        value=payload.get("draft") or "",
        height=260,
        key=widget_key("draft", thread_id),
    )
    action = st.radio(
        "Action",
        choices,
        format_func=lambda name: f"{ACTIONS[name].label} — {ACTIONS[name].description}",
        key=widget_key("action", thread_id),
    )
    if not allowed:
        st.caption(
            f"Regeneration is at its cap of {review.regeneration_cap()} for this ticket, so the "
            "action is not offered — the graph would refuse the click anyway."
        )

    comments = st.text_area("Comments", key=widget_key("comments", thread_id), height=80)
    override_target = None
    if action == "ESCALATE_OVERRIDE":
        override_target = st.text_input(
            "Escalate to", value=payload.get("escalation_target") or "",
            key=widget_key("target", thread_id),
        )
    reviewer = st.text_input("Reviewer", value="reviewer", key=widget_key("who", thread_id))

    if st.button("Submit decision", type="primary", key=widget_key("submit", thread_id)):
        original = payload.get("draft") or ""
        result = review.submit(
            thread_id,
            action,
            comments=comments,
            edited_draft=edited if action == "EDIT" and edited != original else None,
            escalation_target=override_target,
            reviewer=reviewer or "reviewer",
        )
        st.session_state["last_result"] = (
            f"{result.action} recorded for {payload.get('ticket_id')} — "
            + ("sent back for regeneration" if result.regenerated else "run terminated into audit")
        )
        st.session_state.pop("thread_id", None)
        # Rerun rather than mutating the page: the queue below has changed under it.
        st.rerun()


def review_screen() -> None:
    thread_id = st.session_state.get("thread_id")
    if not thread_id:
        st.info("Pick a ticket on the Queue screen.")
        return
    try:
        payload = service().payload(thread_id)
    except InteractiveReviewUnavailable as exc:
        st.error(str(exc))
        return

    st.header(f"{payload.get('ticket_id')} — {(payload.get('ticket') or {}).get('subject')}")
    st.caption(f"thread `{thread_id}` · HITL mode **{payload.get('hitl_mode')}**")
    evidence, decision = st.columns(2)
    with evidence:
        render_evidence_column(payload)
    with decision:
        render_decision_column(payload, thread_id)


# ----------------------------------------------------------------------------- queue screen


def queue_screen() -> None:
    st.header("Awaiting review")
    reviews = service().pending()
    if not reviews:
        st.info(
            "Nothing pending. Queue some tickets from the sidebar, or run "
            "`python -m src.main --sample --hitl interactive`."
        )
        return

    disagreed_only = st.checkbox("Only where the rules and the model disagreed", key="only_dis")
    routes = sorted({r.entry.route for r in reviews if r.entry.route})
    chosen = st.multiselect("Route", routes, default=routes, key="route_filter")

    shown = filter_pending(reviews, routes=chosen, disagreed_only=disagreed_only)
    st.caption(f"{len(shown)} of {len(reviews)} pending · least confident first")
    st.dataframe(pending_summary_rows(shown), use_container_width=True, hide_index=True)

    resumable, drifted = split_by_agreement(reviews)
    if drifted:
        st.warning(
            "The queue file and the checkpointer disagree about "
            f"{len(drifted)} ticket(s): {[r.thread_id for r in drifted]}. The checkpointer is "
            "the one that is right — these cannot be resumed."
        )

    if resumable:
        picked = st.selectbox(
            "Open a ticket",
            [r.thread_id for r in resumable],
            format_func=lambda tid: f"{tid.split(':', 1)[1]}  ({tid})",
            key="queue_pick",
        )
        if st.button("Review this ticket", type="primary", key="queue_open"):
            st.session_state["thread_id"] = picked
            st.rerun()


# --------------------------------------------------------------------------- metrics screen


def metrics_screen() -> None:
    st.header("What review measured")
    st.caption(
        "Every figure is labelled with the HITL mode that produced it, and modes are never "
        "pooled. An auto-mode approval is not evidence about what a human would have done."
    )

    by_mode = service().metrics()
    if not by_mode:
        st.info("No decisions recorded yet — `outputs/reviews.jsonl` is empty.")
    for mode, stats in by_mode.items():
        st.subheader(f"{mode} mode — n = {stats['n']}")
        columns = st.columns(4)
        columns[0].metric("Edit rate", f"{stats['edit_rate']:.3f}")
        columns[1].metric("Override rate", f"{stats['override_rate']:.3f}")
        columns[2].metric(
            "Median edit size", f"{stats['median_edit_size']:.3f}", f"n={stats['edits_measured']}"
        )
        columns[3].metric("Disagreement rate", f"{stats['disagreement_rate']:.3f}")
        st.caption(
            f"actions {stats['action_counts']} · agent routes {stats['route_distribution']} · "
            f"regeneration rate {stats['regeneration_rate']:.3f} · reject rate "
            f"{stats['reject_rate']:.3f}"
        )

    st.divider()
    st.subheader("The scored report")
    st.caption("Read from `src/evaluation/`, which owns every number below. Nothing is recomputed here.")
    report = ReviewService.evaluation_report()
    if report is None:
        st.info("No audit records yet — run some tickets first.")
        return
    st.caption(
        f"run `{report['run_id']}` · config `{report['config_hash']}` · HITL mode "
        f"**{report['hitl_mode']}** · {report['records']} records, "
        f"{report['scored_against_golden']} with full labels"
    )
    st.markdown("**Critical errors (target: zero)**")
    st.json(report["critical_errors"])
    st.dataframe(evaluator_rows(report), use_container_width=True, hide_index=True)

    calibration = confidence_calibration(report)
    if calibration:
        st.markdown("**Confidence calibration**")
        st.dataframe(calibration, use_container_width=True, hide_index=True)


# ----------------------------------------------------------------------------- the sidebar


def sidebar_runner() -> None:
    """Queue tickets for review. A batch blocks the UI, so it reports progress as it goes."""
    with st.sidebar.expander("Queue tickets for review"):
        count = st.number_input("How many", 1, 50, 5, key="run_count")
        if st.button("Run them", key="run_go"):
            from src.graph.graph_state import new_run_id

            tickets = sample_tickets(int(count))
            run_id = new_run_id()
            progress = st.progress(0.0, text=f"run {run_id}")
            for position, ticket in enumerate(tickets, 1):
                service().start_ticket(ticket, run_id=run_id)
                progress.progress(position / len(tickets), text=f"{ticket.ticket_id} queued")
            st.success(f"run {run_id}: {len(tickets)} tickets queued")
            st.rerun()
        st.caption(
            f"checkpointer: `{checkpointer_kind()}` · sqlite is required, because a suspended "
            "review has to survive the process that created it."
        )


def main() -> None:
    st.sidebar.title("Northgate review")
    screen = st.sidebar.radio("Screen", ("Queue", "Review", "Metrics"), key="screen")
    sidebar_runner()
    if st.session_state.get("last_result"):
        st.sidebar.success(st.session_state.pop("last_result"))

    # Said before the screens render, because an empty queue and a queue that cannot be read
    # look identical, and only one of them means "nothing to review".
    problem = service().configuration_problem()
    if problem:
        st.error(problem)

    try:
        {"Queue": queue_screen, "Review": review_screen, "Metrics": metrics_screen}[screen]()
    except InteractiveReviewUnavailable as exc:
        st.error(str(exc))


main()
