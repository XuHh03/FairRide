"""Three agent roles backed by an OpenAI-compatible chat completion endpoint.

The example backend is for local walkthroughs and tests only. It never represents
its hand-written responses as model decisions.
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generic, Protocol, TypeVar
from urllib import error, request

from contracts import AdvocateResult, JudgeResult, ReviewInput, Role


T = TypeVar("T", AdvocateResult, JudgeResult)


@dataclass
class AgentCall(Generic[T]):
    result: T
    usage: dict = field(default_factory=dict)


class AgentBackend(Protocol):
    async def advocate(self, review: ReviewInput, role: Role, question: str | None = None) -> AgentCall[AdvocateResult]: ...

    async def judge(
        self, review: ReviewInput, rider_argument: AdvocateResult,
        driver_argument: AdvocateResult, rebuttals: list[AdvocateResult] | None = None,
        previous_assessment: JudgeResult | None = None,
    ) -> AgentCall[JudgeResult]: ...


@dataclass(frozen=True)
class ModelConfig:
    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: int = 45

    @classmethod
    def from_env(cls) -> "ModelConfig":
        key = os.getenv("FAIRRIDE_API_KEY") or os.getenv("OPENAI_API_KEY")
        model = os.getenv("FAIRRIDE_MODEL")
        if not key or not model:
            raise ValueError("Live review requires FAIRRIDE_API_KEY (or OPENAI_API_KEY) and FAIRRIDE_MODEL")
        return cls(
            api_key=key, model=model,
            base_url=os.getenv("FAIRRIDE_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        )


class ChatClient:
    def __init__(self, config: ModelConfig):
        self.config = config

    async def complete_json(self, instructions: str, payload: dict) -> tuple[dict, dict]:
        return await asyncio.to_thread(self._complete_json, instructions, payload)

    def _complete_json(self, instructions: str, payload: dict) -> tuple[dict, dict]:
        body = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }
        req = request.Request(
            f"{self.config.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                data = json.load(response)
        except (error.HTTPError, error.URLError, TimeoutError) as exc:
            # Never copy response bodies or headers into the activity log.
            raise RuntimeError(f"Model request failed ({type(exc).__name__})") from None
        try:
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("Empty model response")
            return json.loads(content), data.get("usage") or {}
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Model returned an invalid JSON response") from exc


_ADVOCATE_INSTRUCTIONS = """You are the {role} reviewing a ride dispute under the supplied project policy v2.1.
Return one JSON object: role, claims, counterpoints, unanswered_questions. Each claim/counterpoint has statement, evidence_ids, policy_ids; arrays are never null. Role must be exactly {role}. Every claim has at least one source or policy citation.
Represent your assigned side, acknowledge counterevidence, and distinguish allegations from verified facts. Apply only the supplied v2.1 clauses and Python facts: five post-schedule pickup minutes AND both message/call contacts for no-show; route tolerance in km and excess-distance fare, not percentages or the entire fare difference.
Copy only IDs present in supplied evidence or policy clauses. Never cite FACT-* as evidence: cite its underlying source records. Applicable section and precedent IDs such as POLICY-2.3 and POLICY-7.3 are valid; do not invent IDs.
Traffic justification requires the supplied historical traffic records matched to route segment and trip time. Narrative app alerts and driver assertions alone are not historical verification. Never invent missing API data, agreement, credibility scores, or a partial-refund formula.
If answering follow_up_question, answer that specific question from supplied sources. Safety or mandatory policy thresholds require referral, not fault assignment. No hidden reasoning; JSON only."""

_JUDGE_INSTRUCTIONS = """You are the impartial Judge under the supplied project reference Ryde Dispute Resolution Policy v2.1.
Return JSON matching output_schema. Actions are request_rebuttal, final_ruling, human_review. A request needs a question and target roles, no ruling/action amount. Human review has no ruling or proposed_action. Final ruling needs decisive source/policy citations and the relevant supplied precedent clause: compare its facts rather than treating it as this case's answer.
Use policy and Python facts consistently. No-show requires the five-minute post-schedule physical wait, verified arrival, and at least one message AND call before cancellation. Missing contact obligations void the fee even after five minutes; neither uphold_charge nor no_action may retain an invalid fee. Driver no-show without contact permits a separate SGD 5 goodwill credit.
Route tolerance is <=1 km; above 2 km requires human review. For eligible smaller deviations, require historical traffic evidence. An unjustified detour gets full refund of the excess DISTANCE component, represented as partial_refund of the trip with refund_basis=excess_distance_fare. Do not refund time charges or the whole fare. Justified and timely informed/agreed routes retain the fare. A justified but unnotified route is referred because its partial-refund formula is unspecified. Missing/conflicting evidence is not affirmative proof of no congestion.
Safety incidents and disputes above SGD 50 require human review. Route rulings need confidence >=0.80. Either party's fraud flag raises the required threshold to 0.95; the provided required_confidence already reflects that gate. Confidence must consider evidence completeness, policy clarity, precedent alignment and available credibility context; explain its basis, do not invent scores or claim empirical calibration. A flag does not establish fault.
proposed_action.amount_cents is a refund TO the rider; goodwill_credit_cents is separate, both nonnegative integer SGD cents. refund_basis is cancellation_fee or excess_distance_fare. No actual payment or account action is executed.
If previous_assessment is present, answer its exact question using rebuttals. rebuttal_round_complete=true means no additional question is permitted: finalize or refer. Never invent sources, cite FACT-* IDs, or leak hidden reasoning. JSON only."""


class ModelAgentBackend:
    def __init__(self, client: ChatClient | None = None):
        self.client = client or ChatClient(ModelConfig.from_env())

    async def advocate(self, review: ReviewInput, role: Role, question: str | None = None) -> AgentCall[AdvocateResult]:
        payload = {"review": review.model_dump(mode="json"), "follow_up_question": question}
        instructions = _ADVOCATE_INSTRUCTIONS.replace("{role}", role)
        output, usage = await self.client.complete_json(instructions, payload)
        result = AdvocateResult.model_validate(output)
        if result.role != role:
            raise ValueError("Advocate returned the wrong role")
        return AgentCall(result, usage)

    async def judge(
        self, review: ReviewInput, rider_argument: AdvocateResult,
        driver_argument: AdvocateResult, rebuttals: list[AdvocateResult] | None = None,
        previous_assessment: JudgeResult | None = None,
    ) -> AgentCall[JudgeResult]:
        payload = {
            "review": review.model_dump(mode="json"),
            "rider_argument": rider_argument.model_dump(mode="json"),
            "driver_argument": driver_argument.model_dump(mode="json"),
            "rebuttals": [item.model_dump(mode="json") for item in rebuttals or []],
            "previous_assessment": previous_assessment.model_dump(mode="json") if previous_assessment else None,
            "rebuttal_round_complete": previous_assessment is not None,
            "output_schema": JudgeResult.model_json_schema(),
        }
        output, usage = await self.client.complete_json(_JUDGE_INSTRUCTIONS, payload)
        return AgentCall(JudgeResult.model_validate(output), usage)


class ExampleAgentBackend:
    """Deterministic hand-written walkthrough, never a live ruling."""

    def __init__(self):
        path = Path(__file__).resolve().parent / "examples" / "agent_outputs.json"
        self.examples = json.loads(path.read_text())

    async def advocate(self, review: ReviewInput, role: Role, question: str | None = None) -> AgentCall[AdvocateResult]:
        case_examples = self.examples.get(review.case_id)
        if not case_examples:
            raise ValueError(f"Example walkthrough is not available for {review.case_id}")
        if question:
            rebuttal_key = role.removesuffix("_advocate") + "_rebuttal_advocate"
            if rebuttal_key in case_examples:
                return AgentCall(AdvocateResult.model_validate(case_examples[rebuttal_key]))
            # Rebuttal response: cite that the records do not resolve the question
            output = {
                "role": role,
                "claims": [{
                    "statement": "The supplied records do not resolve the material question asked.",
                    "evidence_ids": ["TRIP-001", "TICKET-001"],
                    "policy_ids": ["POLICY-1.4"],
                }],
                "counterpoints": [],
                "unanswered_questions": [question],
            }
        else:
            output = case_examples[role]
        return AgentCall(AdvocateResult.model_validate(output))

    async def judge(
        self, review: ReviewInput, rider_argument: AdvocateResult,
        driver_argument: AdvocateResult, rebuttals: list[AdvocateResult] | None = None,
        previous_assessment: JudgeResult | None = None,
    ) -> AgentCall[JudgeResult]:
        case_examples = self.examples.get(review.case_id)
        if not case_examples:
            raise ValueError(f"Example walkthrough is not available for {review.case_id}")
        if rebuttals is not None:
            key = "judge_human_review" if "judge_human_review" in case_examples else "judge_final_ruling"
        else:
            key = "judge_rebuttal" if "judge_rebuttal" in case_examples else "judge_final_ruling"
        return AgentCall(JudgeResult.model_validate(case_examples[key]))


def rider_advocate(review: ReviewInput) -> AdvocateResult:
    return asyncio.run(ModelAgentBackend().advocate(review, "rider_advocate")).result


def driver_advocate(review: ReviewInput) -> AdvocateResult:
    return asyncio.run(ModelAgentBackend().advocate(review, "driver_advocate")).result


def judge(
    review: ReviewInput, rider_argument: AdvocateResult,
    driver_argument: AdvocateResult, rebuttals: list[AdvocateResult] | None = None,
    previous_assessment: JudgeResult | None = None,
) -> JudgeResult:
    return asyncio.run(ModelAgentBackend().judge(review, rider_argument, driver_argument, rebuttals, previous_assessment)).result
