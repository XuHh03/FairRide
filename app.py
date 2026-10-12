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
case_options = ["DISP-002", "DISP-003", "DISP-004", "DISP-005"]
case_labels = {
    "DISP-002": "DISP-002 — No-show · Ambiguous (driver waited 8 min, entrance unclear)",
    "DISP-003": "DISP-003 — No-show · Rider-favorable (driver late, waited 4 min)",
    "DISP-004": "DISP-004 — No-show · Driver-favorable (driver early, waited 12 min)",
    "DISP-005": "DISP-005 — Route deviation · Rider-favorable (36% longer route)",
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
st.caption("Digital Native track | Sample-policy dispute review prototype")
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
st.info("This is a sample policy, not an official Ryde rule. A result recommends an action; no payment is executed.")

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
    with st.spinner("Reviewing evidence and arguments..."):
        st.session_state.review_result = run_review(case, policy, backend)
        st.session_state.review_mode = mode

result = st.session_state.get("review_result")
if result:
    st.divider()
    st.subheader("Review result")
    st.caption(f"Source: {st.session_state.review_mode}. Sample policy version {policy['version']}.")
    if result.status == "completed":
        st.success(f"Proposed ruling: {result.judge_result.ruling}")
        st.metric("Recommended rider refund", f"S${result.judge_result.proposed_action.amount_cents / 100:.2f}")
    else:
        st.warning("Human review required")
    st.write(result.judge_result.explanation)
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

with st.expander("Full sample policy and source evidence"):
    st.json(policy)
    evidence_sections = {
        k: case[k] for k in
        ("trip_data", "gps_telemetry", "chat_logs", "app_events",
         "route_data", "fare_items")
        if k in case
    }
    st.json(evidence_sections)
