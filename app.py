"""Read-only starting screen for the dispute-review demo."""

import streamlit as st

from case_data import load_case, load_policy
from checks import no_show_facts


st.set_page_config(page_title="FairRide | Dispute review", layout="wide")
case = load_case("DISP-002")
policy = load_policy("sample_no_show")
facts = no_show_facts(case, policy)
ticket = case["dispute_ticket"]

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

st.info("Agent review has not been connected yet. The information below is source evidence, not a ruling.")
with st.expander("Trip and GPS records", expanded=True):
    st.json({"trip_data": case["trip_data"], "gps_telemetry": case["gps_telemetry"]})
with st.expander("Chat and app events"):
    st.json({"chat_logs": case["chat_logs"], "app_events": case["app_events"]})
