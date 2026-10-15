import asyncio
import copy
import json
import unittest

from agents import AgentCall, ExampleAgentBackend, ModelAgentBackend
from case_data import list_demo_trips, load_case, file_dispute, policy_for_case
from contracts import EvidenceRequest
from evidence import build_review_input
from retrieval import LocalEvidenceTools, gather_advocate_evidence
from workflow import run_review


class DisputeIntakeTests(unittest.TestCase):
    def test_complaint_is_attached_to_trip_without_modifying_stored_case(self):
        original = load_case("DISP-010")
        trip_id = original["dispute_ticket"]["trip_id"]
        self.assertIn(trip_id, [trip["trip_id"] for trip in list_demo_trips()])
        case = file_dispute(trip_id, "  I was overcharged for a longer route.  ")
        self.assertEqual(case["dispute_ticket"]["description"], "I was overcharged for a longer route.")
        self.assertEqual(case["route_data"], original["route_data"])
        self.assertEqual(load_case("DISP-010"), original)

    def test_unknown_trip_and_empty_or_overlong_complaint_are_rejected(self):
        trip = load_case("DISP-004")["dispute_ticket"]["trip_id"]
        for trip_id, complaint in (("../unknown", "Wrong fee"), (trip, "  "), (trip, "x" * 2001)):
            with self.subTest(trip=trip_id), self.assertRaises(ValueError):
                file_dispute(trip_id, complaint)


class EvidenceRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case("DISP-010")
        self.review = build_review_input(self.case, policy_for_case(self.case))
        self.tools = LocalEvidenceTools(self.review)

    def test_tools_only_return_selected_trip_sources_without_profiles(self):
        self.assertNotIn("rider_profile", self.tools.available_sources)
        records = self.tools.read(self.tools.trip_id, ["chat_logs"])
        self.assertEqual([record.model_dump() for record in records],
                         [record.model_dump() for record in self.review.evidence if record.source == "chat_logs"])
        for trip, sources in (("TRIP-OTHER", ["chat_logs"]), (self.tools.trip_id, ["rider_profile"]),
                              (self.tools.trip_id, ["../../.env"]), (self.tools.trip_id, [])):
            with self.subTest(trip=trip, sources=sources), self.assertRaises(ValueError):
                self.tools.read(trip, sources)

    def test_model_selects_sources_adaptively_before_receiving_complete_evidence(self):
        payloads, events = [], []
        tools = self.tools

        async def planner(payload):
            payloads.append(copy.deepcopy(payload))
            sources = ["trip_data"] if len(payloads) == 1 else payload["remaining_sources"]
            return AgentCall(EvidenceRequest(trip_id=payload["trip_id"], sources=sources,
                                             purpose="Inspect the trip and corroborating records."), usage={"total_tokens": 4})

        gathered = asyncio.run(gather_advocate_evidence(self.review, "rider_advocate", planner, events.append, lambda message: None))
        self.assertNotIn("evidence", payloads[0])
        self.assertNotIn("facts", payloads[0])
        self.assertEqual(payloads[0]["tool_results"], [])
        serialized = json.dumps(payloads[0])
        self.assertNotIn("rider_profile", serialized)
        self.assertNotIn("expected_ruling", serialized)
        self.assertEqual(payloads[1]["tool_results"][0]["records"][0]["source"], "trip_data")
        self.assertEqual(gathered.model_dump(), self.review.model_dump())
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["record_ids"], [record.id for record in tools.read(tools.trip_id, ["trip_data"])])
        self.assertEqual(events[0]["usage"]["total_tokens"], 4)

    def test_repeated_partial_requests_exhaust_budget_instead_of_hiding_evidence(self):
        calls, events = [], []

        async def planner(payload):
            calls.append(payload)
            return AgentCall(EvidenceRequest(trip_id=payload["trip_id"], sources=["trip_data"], purpose="Read trip."))

        with self.assertRaisesRegex(ValueError, "retrieval budget"):
            asyncio.run(gather_advocate_evidence(self.review, "driver_advocate", planner, events.append, lambda message: None))
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(events), 3)

    def test_cross_trip_request_is_logged_and_rejected(self):
        events = []

        async def planner(payload):
            return AgentCall(EvidenceRequest(trip_id="TRIP-OTHER", sources=["trip_data"], purpose="Read trip."))

        with self.assertRaises(ValueError):
            asyncio.run(gather_advocate_evidence(self.review, "driver_advocate", planner, events.append, lambda message: None))
        self.assertIn("error", events[0])

    def test_live_planner_uses_existing_json_connection_and_request_schema(self):
        class Client:
            async def complete_json(self, instructions, payload):
                self.instructions, self.payload = instructions, payload
                return {"trip_id": "TRIP-ONE", "sources": ["chat_logs"], "purpose": "Check agreement."}, {"total_tokens": 5}

        client = Client()
        call = asyncio.run(ModelAgentBackend(client).plan_evidence({"trip_id": "TRIP-ONE"}))
        self.assertEqual(EvidenceRequest.model_validate(call.result).sources, ["chat_logs"])
        self.assertEqual(call.usage["total_tokens"], 5)
        self.assertEqual(client.payload["output_schema"], EvidenceRequest.model_json_schema())

    def test_malformed_live_request_keeps_failure_duration_and_usage(self):
        events = []

        class Client:
            async def complete_json(self, instructions, payload):
                return {"trip_id": payload["trip_id"], "sources": ["rider_profile"],
                        "purpose": "Read a forbidden source."}, {"total_tokens": 17}

        with self.assertRaises(ValueError):
            asyncio.run(gather_advocate_evidence(self.review, "rider_advocate", ModelAgentBackend(Client()).plan_evidence,
                                                events.append, lambda message: None))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["usage"]["total_tokens"], 17)
        self.assertIsInstance(events[0]["duration_ms"], int)
        self.assertEqual(events[0]["record_ids"], [])
        self.assertIn("error", events[0])

    def test_planner_transport_failure_is_logged_without_invented_usage(self):
        events = []

        async def planner(payload):
            raise RuntimeError("Model request failed (TimeoutError)")

        with self.assertRaises(RuntimeError):
            asyncio.run(gather_advocate_evidence(self.review, "rider_advocate", planner,
                                                events.append, lambda message: None))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["usage"], {})
        self.assertIn("TimeoutError", events[0]["error"])

    def test_both_advocates_retrieve_before_argument_and_judge_sees_full_record(self):
        test, requests, progress = self, [], []

        class Backend(ExampleAgentBackend):
            async def plan_evidence(self, payload):
                requests.append(payload)
                return await super().plan_evidence(payload)

            async def advocate(self, review, role, question=None):
                test.assertTrue(any(payload["role"] == role for payload in requests))
                test.assertEqual(review.model_dump(), test.review.model_dump())
                return await super().advocate(review, role, question)

            async def judge(self, review, *args, **kwargs):
                test.assertEqual(review.model_dump(), test.review.model_dump())
                return await super().judge(review, *args, **kwargs)

        result = run_review(self.case, policy_for_case(self.case), Backend(), gather_evidence=True, on_progress=progress.append)
        self.assertEqual(result.status, "completed")
        events = [event for event in result.activity_log if event.event == "evidence_request"]
        self.assertEqual({event.actor for event in events}, {"rider_advocate", "driver_advocate"})
        self.assertEqual(set(events[0].output["record_ids"]), set(events[1].output["record_ids"]))
        self.assertTrue(any("retrieving evidence" in message for message in progress))
        for role in ("rider_advocate", "driver_advocate"):
            own = [entry.event for entry in result.activity_log if entry.actor == role]
            self.assertLess(own.index("evidence_request"), own.index("initial_argument"))

    def test_retrieval_failure_prevents_judge_and_preserves_request_log(self):
        class Backend(ExampleAgentBackend):
            async def plan_evidence(self, payload):
                return AgentCall(EvidenceRequest(trip_id="TRIP-OTHER", sources=["trip_data"], purpose="Read trip."))

            async def judge(self, *args, **kwargs):
                raise AssertionError("Judge must not run after retrieval fails")

        result = run_review(self.case, policy_for_case(self.case), Backend(), gather_evidence=True)
        self.assertEqual(result.failure_category, "validation")
        self.assertIsNone(result.judge_result.proposed_action)
        self.assertTrue(any(event.event == "evidence_request" for event in result.activity_log))

    def test_live_workflow_retrieves_before_sending_existing_argument_payloads(self):
        examples = ExampleAgentBackend().examples["DISP-010"]
        payloads = []

        class Client:
            async def complete_json(self, instructions, payload):
                payloads.append(copy.deepcopy(payload))
                if "remaining_sources" in payload:
                    return {"trip_id": payload["trip_id"], "sources": payload["remaining_sources"],
                            "purpose": "Inspect the route, fare and communication evidence."}, {"total_tokens": 3}
                if "argument" in payload:
                    return {"findings": []}, {}
                if "rider_argument" in payload:
                    return examples["judge_final_ruling"], {}
                role = "rider_advocate" if "rider_advocate" in instructions else "driver_advocate"
                return examples[role], {}

        case = file_dispute(self.tools.trip_id, "The detour increased my fare.")
        result = run_review(case, policy_for_case(case), ModelAgentBackend(Client()), gather_evidence=True)
        self.assertEqual(result.status, "completed")
        self.assertEqual(len([payload for payload in payloads if "remaining_sources" in payload]), 2)
        for role in ("rider_advocate", "driver_advocate"):
            request = next(payload for payload in payloads if payload.get("role") == role)
            self.assertEqual(request["complaint"], "The detour increased my fare.")
            self.assertNotIn("facts", request)
            self.assertNotIn("review", request)
        for payload in payloads:
            if "review" in payload:
                self.assertEqual(len(payload["review"]["evidence"]), len(self.review.evidence))
                self.assertTrue(payload["review"]["facts"])

    def test_rebuttal_reuses_retrieved_records_without_another_retrieval_round(self):
        class Backend(ExampleAgentBackend):
            requests = 0

            async def plan_evidence(self, payload):
                self.requests += 1
                return await super().plan_evidence(payload)

        backend = Backend()
        case = load_case("DISP-012")
        result = run_review(case, policy_for_case(case), backend, gather_evidence=True)
        self.assertIsNone(result.failure_category)
        self.assertEqual(backend.requests, 2)
        self.assertEqual(sum(entry.event == "rebuttal" for entry in result.activity_log), 2)
        self.assertEqual(sum(entry.event == "evidence_request" for entry in result.activity_log), 2)

    def test_mandatory_policy_referral_still_skips_retrieval(self):
        class Backend(ExampleAgentBackend):
            async def plan_evidence(self, payload):
                raise AssertionError("A mandatory preflight referral should skip model calls")

        case = load_case("DISP-005")
        result = run_review(case, policy_for_case(case), Backend(), gather_evidence=True)
        self.assertTrue(result.mandatory_escalation)
        self.assertIsNone(result.failure_category)
        self.assertFalse(any(entry.event == "evidence_request" for entry in result.activity_log))
