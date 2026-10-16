"""Reviewer dashboard for no-show and route-deviation disputes."""

import json
import os
from hashlib import sha256

import streamlit as st
from dotenv import load_dotenv

from agents import ExampleAgentBackend
from case_data import file_dispute, list_demo_trips, load_case, policy_for_case
from case_import import parse_case_upload
from checks import no_show_facts, route_deviation_facts
from evidence import build_evidence_index, build_policy_index, build_review_input
from review_summary import build_decision_summary, build_review_report, fact_label, format_fact_value
from workflow import run_review


load_dotenv()
st.set_page_config(page_title="FairRide | Dispute review", layout="wide", initial_sidebar_state="expanded")

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

with st.sidebar:
    st.title("FairRide")
    st.caption("Dispute review workspace")
    uploaded_file = st.file_uploader("Import case JSON", type=["json"], max_upload_size=2,
                                     help="One raw no-show or route case. Keep answer keys and evaluation reports separate.")
    imported_case = None
    upload_hash = None
    if uploaded_file is not None:
        content = uploaded_file.getvalue()
        try:
            imported_case = parse_case_upload(content)
        except ValueError as exc:
            st.session_state.pop("review_result", None)
            st.error(f"Import rejected: {exc}")
            st.stop()
        upload_hash = sha256(content).hexdigest()
        st.caption("Imported case is held in this session only. Remove the file to return to demo cases.")
    filing_mode = True if imported_case is not None else st.checkbox("File a dispute", key="filing_mode")
    complaint = ""
    if filing_mode:
        if imported_case is not None:
            imported_ticket = imported_case["dispute_ticket"]
            trip_id = st.selectbox("Select a trip", [imported_ticket["trip_id"]], disabled=True)
            selected_case_id = imported_ticket["dispute_id"]
        else:
            trips = {trip["trip_id"]: trip for trip in list_demo_trips()}
            trip_id = st.selectbox("Select a trip", list(trips))
            selected_case_id = trips[trip_id]["case_id"]
            st.caption("Local demo trips. Each trip has records for its supplied no-show or route-dispute category.")
        complaint = st.text_area("What happened?", value=imported_ticket["description"] if imported_case is not None else "",
                                 max_chars=2000, key=f"complaint_{trip_id}_{upload_hash}" if upload_hash else f"complaint_{trip_id}",
                                 placeholder="The driver took a longer route and I was overcharged.")
    else:
        selected_case_id = st.selectbox("Select a case", list(case_labels))
        st.caption(case_labels[selected_case_id].split(" — ", 1)[1])
    mode = st.radio(
        "Review mode", ["Live model"] if imported_case is not None else ["Example walkthrough", "Live model"],
        help="Example walkthrough uses hand-written fixtures. Live model uses the configured endpoint and credentials.",
    )
    live_ready = bool((os.getenv("FAIRRIDE_API_KEY") or os.getenv("OPENAI_API_KEY")) and os.getenv("FAIRRIDE_MODEL"))
    if mode == "Live model" and not live_ready:
        st.warning("Set FAIRRIDE_API_KEY (or OPENAI_API_KEY) and FAIRRIDE_MODEL to run a live review.")
    if imported_case is not None:
        st.caption("Imported cases use live evidence retrieval. Nothing is sent to the model until you click review.")
    elif filing_mode:
        st.caption("Live model selects evidence sources before arguing. Example walkthrough uses scripted requests and hand-written arguments.")
    run_requested = st.button("File dispute and run review" if filing_mode else "Run review", type="primary", width="stretch",
                              disabled=(mode == "Live model" and not live_ready) or (filing_mode and not complaint.strip()))

input_signature = (selected_case_id, filing_mode, complaint.strip(), upload_hash)
if st.session_state.get("review_input_signature") != input_signature:
    st.session_state.pop("review_result", None)
    st.session_state["selected_case"] = selected_case_id
    st.session_state["review_input_signature"] = input_signature

if imported_case is not None:
    case = file_dispute(trip_id, complaint, imported_case=imported_case) if complaint.strip() else imported_case
else:
    case = file_dispute(trip_id, complaint) if filing_mode and complaint.strip() else load_case(selected_case_id)
policy = policy_for_case(case)
ticket = case["dispute_ticket"]
dtype = ticket["dispute_type"]
sources = build_evidence_index(case)
clauses = build_policy_index(policy)
facts = no_show_facts(case, policy) if dtype == "no_show_charge" else route_deviation_facts(case, policy)
derived_facts = {fact.id: fact for fact in build_review_input(case, policy).facts}

st.title("No-show charge" if dtype == "no_show_charge" else "Route deviation")
st.caption(f"{selected_case_id} · Supplied project policy v{policy['version']}")

if run_requested:
    backend = ExampleAgentBackend() if mode == "Example walkthrough" else None
    with st.status("Preparing review…", expanded=True) as review_progress:
        def show_progress(message: str) -> None:
            review_progress.update(label=message)
            review_progress.write(message)

        review_result = run_review(case, policy, backend, on_progress=show_progress, gather_evidence=filing_mode)
        st.session_state.review_result = review_result
        st.session_state.review_mode = mode
        st.session_state.dashboard_view = "Overview"
        label = "Review complete" if review_result.status == "completed" else "Human review required"
        if review_result.failure_category:
            label = "Review failed; human review required"
        review_progress.update(label=label, state="error" if review_result.failure_category else "complete", expanded=False)

result = st.session_state.get("review_result")
summary = build_decision_summary(case, policy, result) if result else None

with st.sidebar:
    st.divider()
    view = st.radio("View", ["Overview", "Evidence", "Agent activity", "Sources & policy"], key="dashboard_view")
    if result:
        st.divider()
        st.caption(f"Last review: {st.session_state.review_mode}")
        st.download_button(
            "Download review report (JSON)",
            data=json.dumps(build_review_report(case, policy, result, st.session_state.review_mode), indent=2, ensure_ascii=False),
            file_name=f"{selected_case_id}-review.json", mime="application/json", width="stretch",
        )
    st.divider()
    st.caption("Demo records are synthetic. Recommendations do not execute payments or account actions.")


def show_source(source_id: str) -> None:
    if source_id in sources:
        st.caption(sources[source_id].source.replace("_", " ").title())
        st.json(sources[source_id].data)
    elif source_id in clauses:
        st.write(clauses[source_id].text)


def show_citations(ids: list[str]) -> None:
    """Open a cited record in place, without losing the selected dashboard view."""
    if ids:
        with st.container(horizontal=True, gap="small"):
            for source_id in dict.fromkeys(ids):
                with st.popover(source_id):
                    show_source(source_id)


def show_decision() -> None:
    st.subheader("Decision summary")
    if not result:
        st.info("Choose a review mode in the sidebar and run the review to see the recommendation.")
        return
    st.caption(f"Source: {st.session_state.review_mode}")
    if result.failure_category:
        st.error("Model response failed validation" if result.failure_category == "validation" else "Review could not be completed")
        st.caption("No validated decision was issued. This is an operational failure, not a finding that the evidence is insufficient.")
    elif result.status == "completed":
        st.success(summary["outcome"])
        refund, credit = st.columns(2)
        refund.metric("Recommended rider refund", f"S${summary['refund_cents'] / 100:.2f}")
        credit.metric("Separate goodwill credit", f"S${summary['goodwill_credit_cents'] / 100:.2f}")
        if result.judge_result.confidence is not None:
            st.caption(f"Agent-reported confidence: {result.judge_result.confidence:.0%}")
            st.caption("Self-reported by the Judge; not a calibrated probability of correctness.")
    else:
        st.warning("Human review required")
    if result.status == "completed" and not result.failure_category:
        st.caption("Application-generated explanation from validated case facts and policy checks. Original Judge analysis is available in Agent activity.")
    party_messages = summary.get("party_messages")
    if party_messages:
        rider_tab, driver_tab = st.tabs(["For the rider", "For the driver"])
        for tab, role in ((rider_tab, "rider"), (driver_tab, "driver")):
            with tab:
                message = party_messages[role]
                st.markdown(f"**Recommended action:** {message['action']}")
                st.markdown("**Why this decision:**")
                st.write(message["explanation"])
    else:
        st.write(summary["reason"])
    if result.mandatory_escalation:
        st.caption("Human review is required by the governing policy.")
    for flag in result.account_review_flags:
        st.warning(flag)
    if summary["review_issues"]:
        with st.expander(f"Review issues ({len(summary['review_issues'])})", expanded=True):
            for issue in summary["review_issues"]:
                st.write(f"- {issue}")


def show_fact_assertion(assertion: dict) -> None:
    fact = derived_facts[assertion["fact_id"]]
    st.caption(f"Checked fact · {fact_label(fact)}: {format_fact_value(assertion['value'], fact.unit)} ({fact.id})")


def show_calculations() -> None:
    st.subheader("Verified calculations")
    for calculation in summary["calculations"]:
        st.markdown(f"**{calculation['label']}**")
        st.write(calculation["formula"])
        show_citations(calculation["evidence_ids"] + calculation["policy_ids"])
    if dtype == "route_deviation":
        st.caption("The calculated fare component is not an automatic refund. Justification, consent and referral gates also apply.")


def show_route_distance_chart() -> None:
    """Compare measured extra distance with policy boundaries, without implying fault."""
    extra = facts["deviation_km"]
    tolerance = policy["tolerance_km"]
    ai_limit = policy["max_ai_deviation_km"]
    st.subheader("Distance against policy limits")
    st.vega_lite_chart(spec={
        "height": 100,
        "encoding": {
            "x": {"field": "distance", "type": "quantitative",
                  "scale": {"domain": [min(0, extra), max(extra, tolerance, ai_limit) * 1.15]},
                  "axis": {"title": "Additional distance (km)"}},
        },
        "layer": [
            {"data": {"values": [{"distance": extra}]},
             "mark": {"type": "bar", "color": "#2563eb", "height": 24},
             "encoding": {"x2": {"datum": 0}, "y": {"value": 60},
                          "tooltip": [{"field": "distance", "type": "quantitative", "title": "Actual − planned (km)"}]}},
            {"data": {"values": [
                {"distance": tolerance, "boundary": f"No-refund tolerance: ≤{tolerance:g} km"},
                {"distance": ai_limit, "boundary": f"AI distance limit: ≤{ai_limit:g} km"},
            ]},
             "mark": {"type": "rule", "strokeDash": [5, 4], "strokeWidth": 2},
             "encoding": {"y": {"value": 15}, "y2": {"value": 95},
                          "color": {"field": "boundary", "type": "nominal",
                                    "scale": {"domain": [f"No-refund tolerance: ≤{tolerance:g} km", f"AI distance limit: ≤{ai_limit:g} km"],
                                              "range": ["#64748b", "#d97706"]},
                                    "legend": {"title": None, "orient": "top"}},
                          "tooltip": [{"field": "boundary", "type": "nominal", "title": "Policy boundary"}]}},
        ],
    }, width="stretch")
    st.caption(f"Blue bar: {extra:g} km actual − planned distance. Exactly {ai_limit:g} km meets the distance limit. Other policy and evidence checks still apply.")


if view == "Overview":
    st.write(ticket["description"])
    first, second = st.columns(2)
    if dtype == "no_show_charge":
        first.metric("Recorded driver wait", f"{facts['waited_minutes']:g} min")
        second.metric("Cancellation fee", f"S${case['trip_data']['cancellation_fee']:.2f}")
    else:
        first.metric("Additional distance", f"{facts['deviation_km']:g} km")
        second.metric("Excess-distance fare component", f"S${facts['excess_distance_cents'] / 100:.2f}")
    with st.container(border=True):
        show_decision()
    if dtype == "route_deviation":
        show_route_distance_chart()
    if summary:
        checklist, calculations = st.columns([3, 2], gap="large")
        with checklist:
            st.subheader("Policy checklist")
            st.dataframe(
                [{"Condition": item["condition"], "Status": item["status"].capitalize(), "Observed evidence": item["observation"]}
                 for item in summary["checklist"]], hide_index=True, width="stretch",
            )
            st.caption("A failed condition alone does not determine the outcome. Select Evidence in the sidebar for supporting records.")
        with calculations:
            show_calculations()

elif view == "Evidence":
    st.subheader("Evidence")
    if not summary:
        st.info("Run a review to prepare the policy checklist and evidence timeline. Raw records are available under Sources & policy.")
    else:
        st.caption("Prepared from recorded evidence and Python policy checks.")
        checks, timeline, derived = st.tabs(["Policy checks", "Timeline", "Derived facts"])
        with checks:
            for check in summary["checklist"]:
                with st.container(border=True):
                    st.markdown(f"**{check['condition']}** — {check['status'].capitalize()}")
                    st.write(check["observation"])
                    show_citations(check["evidence_ids"] + check["policy_ids"])
        with timeline:
            for event in summary["timeline"]:
                st.write(f"{event['timestamp']} · {event['event']}")
                show_citations(event["evidence_ids"])
        with derived:
            st.caption("Application-derived facts from the selected case's records and policy. Matching a fact value does not validate an agent's entire claim.")
            st.dataframe(
                [{"Fact ID": fact.id, "Meaning": fact_label(fact), "Value": format_fact_value(fact.value, fact.unit)}
                 for fact in derived_facts.values()], hide_index=True, width="stretch",
            )
            st.caption("Expand a fact to inspect its raw value, calculation and supporting sources. Fare components are not automatic refund recommendations.")
            for fact in derived_facts.values():
                with st.expander(f"{fact.id} · {fact_label(fact)}"):
                    st.write(f"Raw value: {fact.value} ({fact.unit})")
                    st.write(fact.formula)
                    show_citations(fact.evidence_ids + fact.policy_ids)

elif view == "Agent activity":
    st.subheader("Agent activity")
    if not result:
        st.info("Run a review to see agent activity.")
    else:
        st.caption("Citation IDs and declared fact values are checked; free-text explanations are not semantically certified.")
        total_ms = prompt_tokens = completion_tokens = 0
        wall_ms = None
        for entry in result.activity_log:
            output = entry.output
            wall_ms = output.get("wall_duration_ms", wall_ms)
            total_ms += output.get("duration_ms", 0)
            usage = output.get("usage", {})
            prompt_tokens += usage.get("prompt_tokens", 0)
            completion_tokens += usage.get("completion_tokens", 0)
            with st.expander(f"{entry.actor.replace('_', ' ').title()} · {entry.event.replace('_', ' ')}"):
                if entry.event == "evidence_request":
                    st.caption("Scripted evidence retrieval" if st.session_state.review_mode == "Example walkthrough" else
                               "Model-selected evidence retrieval")
                    st.caption(f"Trip: {output['trip_id']} · Round {output['round']}/3")
                    st.write("Requested sources: " + ", ".join(source.replace("_", " ") for source in output["sources"]))
                    st.write(output["purpose"])
                    show_citations(output["record_ids"])
                    if output.get("error"):
                        st.error(output["error"])
                if entry.event == "argument_support_review":
                    st.write(f"{output['role'].replace('_', ' ').title()} support check · attempt {output['attempt']}")
                    if not any(finding["verdict"] == "unsupported" for finding in output["findings"]):
                        st.caption("The model support check found no unsupported statements; this does not guarantee factual accuracy.")
                    for finding in output["findings"]:
                        message = f"{finding['section']}.{finding['index']} · {finding['verdict']}: {finding['explanation']}"
                        if finding["verdict"] == "unsupported":
                            st.warning(message)
                        else:
                            st.caption(message)
                        ids = finding["evidence_ids"] + finding["policy_ids"]
                        st.caption("Sources: " + ", ".join(ids))
                        show_citations(ids)
                if entry.event == "decision_validation":
                    st.write("The Judge's response failed these checks and was sent for one correction attempt:")
                    for issue in output["errors"]:
                        st.write(f"- {issue}")
                if output.get("citation_retries"):
                    st.caption("One citation-correction retry was used; token totals include both calls.")
                if output.get("schema_retries"):
                    st.caption("One response-format, fact-value or known prose-consistency correction retry was used; token totals include both calls.")
                for mapping in output.get("citation_resolutions", []):
                    st.caption(f"Resolved {mapping['fact_id']} in {mapping['location']} to sources: " + ", ".join(mapping["evidence_ids"]))
                if "question" in output:
                    st.write(output["question"])
                if "reasons" in output:
                    for reason in output["reasons"]:
                        st.write(reason)
                if "result" in output:
                    item = output["result"]
                    if "claims" in item:
                        st.caption("Model-generated argument; check its interpretation against cited sources." if st.session_state.review_mode == "Live model" else
                                   "Hand-written example argument; not a live model response.")
                        if output.get("support_status") == "flagged":
                            st.warning("This argument was flagged by the support check. Inspect its findings below; it was not accepted for the Judge.")
                        elif output.get("support_status") == "review_failed":
                            st.warning("The support check failed validation. This argument was not accepted for the Judge.")
                        elif output.get("support_status") == "passed_model_review":
                            st.caption("Passed the model support check; source inspection remains available.")
                        for heading in ("claims", "counterpoints"):
                            if item[heading]:
                                st.markdown(f"**{heading.title()}**")
                            for claim in item[heading]:
                                st.write(claim["statement"])
                                show_citations(claim["evidence_ids"] + claim["policy_ids"])
                                for assertion in claim.get("fact_assertions", []):
                                    show_fact_assertion(assertion)
                        if item["unanswered_questions"]:
                            st.write("**Open questions:** " + "; ".join(item["unanswered_questions"]))
                    else:
                        st.caption("Original Judge analysis; model prose may contain errors." if st.session_state.review_mode == "Live model" else
                                   "Original Judge analysis from the hand-written example.")
                        st.write(item["explanation"])
                        if item.get("question"):
                            st.write("**Question:** " + item["question"])
                        show_citations(item["evidence_ids"] + item["policy_ids"])
                        for assertion in item.get("fact_assertions", []):
                            show_fact_assertion(assertion)
                if "duration_ms" in output:
                    st.caption(f"Duration: {output['duration_ms']} ms · Tokens: {usage.get('total_tokens', 'n/a')}")
        st.caption(f"Wall time: {wall_ms if wall_ms is not None else 'n/a'} ms · Model stage time (sum): {total_ms} ms · Prompt tokens: {prompt_tokens} · Completion tokens: {completion_tokens}")

elif view == "Sources & policy":
    st.subheader("Sources & policy")
    evidence_tab, policy_tab = st.tabs(["Source records", "Governing policy"])
    with evidence_tab:
        source_type = st.selectbox("Evidence category", sorted({record.source for record in sources.values()}), format_func=lambda value: value.replace("_", " ").title())
        for source_id, record in sources.items():
            if record.source == source_type:
                with st.expander(source_id):
                    show_source(source_id)
    with policy_tab:
        st.caption(f"Supplied RydeResolve project reference v{policy['version']}")
        for source_id in clauses:
            with st.expander(source_id):
                show_source(source_id)
        with st.expander("Complete policy record"):
            st.json(policy)
