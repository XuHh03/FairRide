"""Reviewer walkthrough for no-show and route-deviation disputes."""

import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # Load .env for FAIRRIDE_API_KEY, FAIRRIDE_BASE_URL, etc.

from agents import ExampleAgentBackend
from case_data import load_case, policy_for_case
from checks import no_show_facts, route_deviation_facts
from evidence import build_evidence_index, build_policy_index
from workflow import run_review


st.set_page_config(page_title="FairRide | Dispute review", layout="wide")

# Case selector — switch between all supported dispute cases
case_options = [f"DISP-{number:03d}" for number in range(2, 13)]
case_labels = {
    "DISP-002": "DISP-002 — No-show · Recorded arrival and both contacts",
    "DISP-003": "DISP-003 — No-show · Late arrival and missing call",
    "DISP-004": "DISP-004 — No-show · Both contact obligations met",
    "DISP-005": "DISP-005 — Route deviation · Above 2 km AI limit",
    "DISP-006": "DISP-006 — Route deviation · 2 km, no congestion",
    "DISP-007": "DISP-007 — No-show · Five-minute wait, missing call",
    "DISP-008": "DISP-008 — Route deviation · Justified, above AI limit",
    "DISP-009": "DISP-009 — Route deviation · Large and conflicting records",
    "DISP-010": "DISP-010 — Route deviation · 1.5 km, unjustified",
    "DISP-011": "DISP-011 — Route deviation · 1.5 km, verified and agreed",
    "DISP-012": "DISP-012 — Route deviation · Conflicting traffic history",
}
selected_case_id = st.selectbox(
    "Select a case", case_options,
    format_func=lambda cid: case_labels[cid],
)
# Clear previous result when switching cases
if st.session_state.get("selected_case") != selected_case_id:
    st.session_state.pop("review_result", None)
    st.session_state["selected_case"] = selected_case_id

case = load_case(selected_case_id)
policy = policy_for_case(case)
ticket = case["dispute_ticket"]
dtype = ticket["dispute_type"]
sources = build_evidence_index(case)
clauses = build_policy_index(policy)

# Compute type-specific facts
if dtype == "no_show_charge":
    facts = no_show_facts(case, policy)
elif dtype == "route_deviation":
    facts = route_deviation_facts(case, policy)
else:
    raise ValueError(f"Unsupported dispute type: {dtype}")

# Friendly display labels per dispute type
dispute_titles = {
    "no_show_charge": "No-show charge",
    "route_deviation": "Route deviation",
}

st.title("FairRide")
st.caption("Digital Native track | Project reference v2.1 | Dispute review prototype")
st.subheader(f"{ticket['dispute_id']}: {dispute_titles.get(dtype, dtype)}")
st.write(ticket["description"])

left, right = st.columns(2)
if dtype == "no_show_charge":
    left_metric_label = "Recorded driver wait"
    left_metric_value = f"{facts['waited_minutes']:g} min"
    right_metric_label = "Cancellation fee"
    right_metric_value = f"S${case['trip_data']['cancellation_fee']:.2f}"
elif dtype == "route_deviation":
    left_metric_label = "Route deviation"
    left_metric_value = f"{facts['deviation_pct']:.1f}%"
    right_metric_label = "Fare difference"
    right_metric_value = f"S${facts['fare_difference']:.2f}"
with left:
    st.metric(left_metric_label, left_metric_value)
with right:
    st.metric(right_metric_label, right_metric_value)
st.info("Governing reference: supplied RydeResolve policy v2.1. Demo records are synthetic. Recommendations do not execute payments or account actions.")

live_ready = bool((os.getenv("FAIRRIDE_API_KEY") or os.getenv("OPENAI_API_KEY")) and os.getenv("FAIRRIDE_MODEL"))
mode = st.radio(
    "Review mode",
    ["Example walkthrough", "Live model"], horizontal=True,
    help="Example walkthrough uses hand-written fixtures. Live model uses the configured endpoint and credentials.",
)
if mode == "Live model" and not live_ready:
    st.warning("Set FAIRRIDE_API_KEY (or OPENAI_API_KEY) and FAIRRIDE_MODEL to run a live review.")

if st.button("Run review", disabled=mode == "Live model" and not live_ready):
    backend = ExampleAgentBackend() if mode == "Example walkthrough" else None
    with st.status("Preparing review…", expanded=True) as review_progress:
        def show_progress(message: str) -> None:
            review_progress.update(label=message)
            review_progress.write(message)

        review_result = run_review(case, policy, backend, on_progress=show_progress)
        st.session_state.review_result = review_result
        st.session_state.review_mode = mode
        label = "Review complete" if review_result.status == "completed" else "Human review required"
        if review_result.failure_category:
            label = "Review failed; human review required"
        review_progress.update(label=label, state="error" if review_result.failure_category else "complete")

result = st.session_state.get("review_result")
if result:
    st.divider()
    st.subheader("Review result")
    st.caption(f"Source: {st.session_state.review_mode}. Project policy version {policy['version']}.")
    if result.status == "completed":
        st.success(f"Proposed ruling: {result.judge_result.ruling}")
        st.metric("Recommended rider refund", f"S${result.judge_result.proposed_action.amount_cents / 100:.2f}")
        if result.judge_result.proposed_action.goodwill_credit_cents:
            st.metric("Separate goodwill credit", f"S${result.judge_result.proposed_action.goodwill_credit_cents / 100:.2f}")
        if result.judge_result.confidence is not None:
            st.caption(f"Agent-reported confidence: {result.judge_result.confidence:.0%}")
    elif result.failure_category:
        st.error("Model response failed validation" if result.failure_category == "validation" else "Review could not be completed")
        st.caption("No validated decision was issued. This is an operational failure, not a finding that the evidence is insufficient.")
    else:
        st.warning("Human review required")
    if result.final_explanation:
        st.caption("Application-generated explanation from validated case facts and policy checks. Original Judge analysis is available below.")
        st.write(result.final_explanation)
    else:
        st.write(result.judge_result.explanation)
    for flag in result.account_review_flags:
        st.warning(flag)
    if result.mandatory_escalation:
        st.caption("Human review is required by the governing policy.")
    if result.validation_issues:
        st.write("**Review issues**")
        for issue in result.validation_issues:
            st.write(f"- {issue}")

    st.subheader("Agent activity")
    cited = set(result.judge_result.evidence_ids + result.judge_result.policy_ids)
    total_ms = 0
    prompt_tokens = 0
    completion_tokens = 0
    wall_ms = None
    for entry in result.activity_log:
        output = entry.output
        if "wall_duration_ms" in output:
            wall_ms = output["wall_duration_ms"]
        total_ms += output.get("duration_ms", 0)
        usage = output.get("usage", {})
        prompt_tokens += usage.get("prompt_tokens", 0)
        completion_tokens += usage.get("completion_tokens", 0)
        with st.expander(f"{entry.actor.replace('_', ' ').title()} · {entry.event.replace('_', ' ')}", expanded=True):
            if entry.event == "decision_validation":
                st.write("The Judge's response failed these checks and was sent for one correction attempt:")
                for issue in output["errors"]:
                    st.write(f"- {issue}")
            if output.get("citation_retries"):
                st.caption("One citation-correction retry was used; token totals include both calls.")
            if output.get("schema_retries"):
                st.caption("One response-format correction retry was used; token totals include both calls.")
            for mapping in output.get("citation_resolutions", []):
                st.caption(f"Resolved {mapping['fact_id']} in {mapping['location']} to sources: " + ", ".join(mapping["evidence_ids"]))
            if "question" in output:
                st.write(output["question"])
            if "result" in output:
                item = output["result"]
                if "claims" in item:
                    for heading in ("claims", "counterpoints"):
                        if item[heading]:
                            st.write(f"**{heading.title()}**")
                        for claim in item[heading]:
                            st.write(claim["statement"])
                            ids = claim["evidence_ids"] + claim["policy_ids"]
                            st.caption("Sources: " + ", ".join(ids))
                            cited.update(ids)
                    if item["unanswered_questions"]:
                        st.write("**Open questions:** " + "; ".join(item["unanswered_questions"]))
                else:
                    st.write(item["explanation"])
                    if item.get("question"):
                        st.write("**Question:** " + item["question"])
                    ids = item["evidence_ids"] + item["policy_ids"]
                    st.caption("Sources: " + ", ".join(ids))
                    cited.update(ids)
            if "duration_ms" in output:
                st.caption(f"Duration: {output['duration_ms']} ms · Tokens: {usage.get('total_tokens', 'n/a')}")
    st.caption(
        f"Wall time: {wall_ms if wall_ms is not None else 'n/a'} ms · "
        f"Model stage time (sum): {total_ms} ms · "
        f"Prompt tokens: {prompt_tokens} · Completion tokens: {completion_tokens}"
    )

    st.subheader("Cited source records")
    for source_id in sorted(cited):
        with st.expander(source_id):
            if source_id in sources:
                st.caption(sources[source_id].source)
                st.json(sources[source_id].data)
            elif source_id in clauses:
                st.write(clauses[source_id].text)

with st.expander("Governing policy and source evidence"):
    st.json(policy)
    evidence_sections = {
        k: case[k] for k in
        ("trip_data", "gps_telemetry", "chat_logs", "app_events",
         "route_data", "fare_items", "traffic_data")
        if k in case
    }
    st.json(evidence_sections)
