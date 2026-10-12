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


_ADVOCATE_INSTRUCTIONS = """You are the {role} in a sample rider-driver dispute review.

Return ONE JSON object with EXACTLY these top-level fields:
- "role": must be exactly "{role}"
- "claims": array of objects. Each object has "statement" (non-empty string), "evidence_ids" (array of strings), "policy_ids" (array of strings).
- "counterpoints": same structure as claims.
- "unanswered_questions": array of strings.

Example (copy the structure, fill with real content from the records):
  {
    "role": "{role}",
    "claims": [
      {"statement": "The driver arrived late.", "evidence_ids": ["TRIP-001"], "policy_ids": ["POLICY-003"]}
    ],
    "counterpoints": [
      {"statement": "The rider was not at the pickup.", "evidence_ids": ["CHAT-002"], "policy_ids": ["POLICY-001"]}
    ],
    "unanswered_questions": ["Was the designated entrance clearly communicated?"]
  }

Field rules:
- All array fields (claims, counterpoints, unanswered_questions) must be JSON arrays. Never use null. Use [] when empty.
- Each claim and counterpoint must have at least one entry in evidence_ids or policy_ids.
- "statement" must be a non-empty string.

Evidence ID rules:
- Copy evidence IDs exactly as they appear in the supplied records. Each ID has exactly ONE prefix and ONE number.
- Valid prefixes: GPS-, CHAT-, EVENT-, TRIP-, TICKET-. Policy IDs use POLICY-.
- Example correct IDs: GPS-005, CHAT-003, EVENT-004, TRIP-001, TICKET-001, POLICY-003.
- NEVER combine or merge prefixes. "CHATTICKET-001" is INVALID. To cite a chat and a ticket, use ["CHAT-001", "TICKET-001"].
- Do NOT cite derived fact IDs (FACT-*); they are computed context, not citable sources.

Conduct:
- Represent uncertainty and the opposing side fairly. A citation must support the exact statement.
- Never infer a rider's location from driver GPS, decide from profile history, or treat the sample policy as official.
- If asked a follow-up question, answer only from supplied records and say when they cannot answer it.
- No hidden reasoning or invented records. Return JSON only, no markdown."""

_JUDGE_INSTRUCTIONS = """You are an impartial reviewer of a sample rider-driver dispute.

Return ONE JSON object with EXACTLY these fields:
{
  "action": "final_ruling",
  "question": null,
  "rebuttal_roles": [],
  "ruling": "uphold_charge",
  "proposed_action": {"amount_cents": 0, "currency": "SGD"},
  "explanation": "Your reasoning here.",
  "evidence_ids": ["GPS-005"],
  "policy_ids": ["POLICY-003"],
  "confidence": 0.85
}

Action rules (choose one):
- "request_rebuttal": Set question to a non-empty string and rebuttal_roles to ["rider_advocate"] or ["driver_advocate"]. Set ruling to null and omit proposed_action.
- "final_ruling": Set ruling to one of: "uphold_charge", "reverse_charge", "partial_refund", "no_action". Set proposed_action.amount_cents. Set question to null and rebuttal_roles to [].
- "human_review": Set ruling to null and omit proposed_action. Set question to null and rebuttal_roles to [].

Field rules:
- All array fields (rebuttal_roles, evidence_ids, policy_ids) must be JSON arrays. Never use null for arrays. Use [] when empty.
- question must be null when action is not request_rebuttal. Do NOT send an empty string "".
- proposed_action must be present ONLY for final_ruling. Omit it (or set to null) for other actions.
- explanation must be a non-empty string.
- confidence is a number between 0.0 and 1.0. Use null if you have none.

Evidence ID rules:
- Copy evidence IDs exactly as they appear in the supplied records. Each ID has exactly ONE prefix and ONE number.
- Valid prefixes: GPS-, CHAT-, EVENT-, TRIP-, TICKET-. Policy IDs use POLICY-.
- Example correct IDs: GPS-005, CHAT-003, EVENT-004, TRIP-001, TICKET-001, POLICY-003.
- NEVER combine or merge prefixes. "CHATTICKET-001" is INVALID. To cite a chat and a ticket, use ["CHAT-001", "TICKET-001"].
- Do NOT cite derived fact IDs (FACT-*); they are computed context, not citable sources.

Amount rules (amount_cents is the SGD refund TO the rider, in integer cents):
- "uphold_charge": 0 (no refund)
- "reverse_charge": full charge amount (500 for S$5.00)
- "partial_refund": between 0 and the full charge (exclusive)

Decision guidance:
- The review includes Python-calculated facts (waited_minutes, fee_eligible). Use them to guide your ruling.
- If fee_eligible is true and the driver waited at or beyond the no-show threshold, uphold_charge (0 refund) is appropriate.
- If fee_eligible is false (driver waited below the threshold), reverse_charge (full refund) is appropriate.
- Make a final_ruling when the calculated facts clearly support one side. Do not abstain merely because GPS does not prove the rider's exact position — the wait-time threshold is the decisive factor.
- Route to human_review ONLY when material evidence is genuinely missing, contradictory, or the case is truly ambiguous after considering the calculated facts.
- Source-ID existence alone is not proof. Treat the sample policy as not official.
- Never use rider/driver history or invent records. Return JSON only, no markdown."""


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
    ) -> AgentCall[JudgeResult]:
        payload = {
            "review": review.model_dump(mode="json"),
            "rider_argument": rider_argument.model_dump(mode="json"),
            "driver_argument": driver_argument.model_dump(mode="json"),
            "rebuttals": [item.model_dump(mode="json") for item in rebuttals or []],
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
            # Rebuttal response: cite that the records do not resolve the question
            output = {
                "role": role,
                "claims": [{
                    "statement": "The supplied records do not resolve the material question asked.",
                    "evidence_ids": ["TRIP-001", "TICKET-001"],
                    "policy_ids": ["POLICY-005"],
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
) -> JudgeResult:
    return asyncio.run(ModelAgentBackend().judge(review, rider_argument, driver_argument, rebuttals)).result
