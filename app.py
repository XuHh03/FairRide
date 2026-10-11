"""Dispute-review demo for the FairRide prototype."""

import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # Load .env for FAIRRIDE_API_KEY, FAIRRIDE_BASE_URL, etc.

from case_data import load_case, load_policy
from checks import no_show_facts
from evidence import build_evidence_index


def _render_advocate_output(output: dict, ev_index: dict):
    """Render advocate claims with expandable evidence citations."""
    for kind in ("claims", "counterpoints"):
        items = output.get(kind, [])
        if not items:
            continue
        st.write(f"*{kind.title()}*")
        for item in items:
            statement = item.get("statement", "")
            evidence_ids = item.get("evidence_ids", [])
            policy_ids = item.get("policy_ids", [])
            st.write(f"- {statement}")
            if evidence_ids:
                for eid in evidence_ids:
                    record = ev_index.get(eid)
                    if record:
                        with st.expander(f"  {eid} ({record.source})"):
                            st.json(record.data)
                    else:
                        st.caption(f"  {eid} (unknown)")
            if policy_ids:
                st.caption(f"  Policy: {', '.join(policy_ids)}")

    questions = output.get("unanswered_questions", [])
    if questions:
        st.write("*Unanswered questions*")
        for q in questions:
            st.write(f"- {q}")


def _render_result(result_data: dict, ev_index: dict):
    """Render the full review result: status, judge summary, issues, activity log."""
    status = result_data["status"]
    judge = result_data["judge_result"]

    if status == "completed":
        st.success(f"Status: {status}")
    else:
        st.warning(f"Status: {status}")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Judge action", judge.get("action", "—"))
    with col2:
        ruling = judge.get("ruling") or "—"
        st.metric("Ruling", ruling)
    with col3:
        action_obj = judge.get("proposed_action") or {}
        amount = action_obj.get("amount_cents", 0)
        st.metric("Proposed refund", f"S${amount / 100:.2f}")

    if judge.get("confidence") is not None:
        st.metric("Confidence", f"{judge['confidence']:.2f}")

    st.write("**Explanation**")
    st.write(judge.get("explanation", ""))

    issues = result_data.get("validation_issues", [])
    if issues:
        st.error("Validation issues detected:")
        for issue in issues:
            st.write(f"- {issue}")

    st.write("**Activity log**")
    for i, entry in enumerate(result_data["activity_log"], 1):
        actor = entry["actor"]
        event = entry["event"]
        output = entry["output"]
        label = f"{i}. [{actor}] {event}"

        with st.expander(label):
            if actor in ("rider_advocate", "driver_advocate"):
                _render_advocate_output(output, ev_index)
            else:
                st.json(output)


st.set_page_config(page_title="FairRide | Dispute review", layout="wide")

# Case selector — switch between all no-show cases
case_options = ["DISP-002", "DISP-003", "DISP-004"]
case_labels = {
    "DISP-002": "DISP-002 — Ambiguous (driver waited 8 min, entrance unclear)",
    "DISP-003": "DISP-003 — Rider-favorable (driver late, waited 4 min)",
    "DISP-004": "DISP-004 — Driver-favorable (driver early, waited 12 min)",
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
policy = load_policy("sample_no_show")
facts = no_show_facts(case, policy)
ticket = case["dispute_ticket"]
evidence_index = build_evidence_index(case)

st.title("FairRide")
st.caption("Digital Native track | Dispute-review prototype")
st.subheader(f"{ticket['dispute_id']}: No-show charge")
st.write(ticket["description"])

left, right = st.columns(2)
with left:
    st.metric("Recorded driver wait", f"{facts['waited_minutes']:g} min")
    st.metric("Cancellation fee", f"S${case['trip_data']['cancellation_fee']:.2f}")
with right:
    st.write("**Sample policy**")
    st.json(policy)

with st.expander("Trip and GPS records", expanded=True):
    st.json({"trip_data": case["trip_data"], "gps_telemetry": case["gps_telemetry"]})
with st.expander("Chat and app events"):
    st.json({"chat_logs": case["chat_logs"], "app_events": case["app_events"]})

st.divider()
st.subheader("Agent review")

if st.button("Run review", type="primary"):
    with st.spinner("Running advocate agents and judge..."):
        from workflow import run_review

        result = run_review(case, policy)
        st.session_state["review_result"] = result.model_dump(mode="json")

if "review_result" in st.session_state:
    _render_result(st.session_state["review_result"], evidence_index)
