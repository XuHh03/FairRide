"""One model API connection. Reads config from env vars; no keys in the repo."""

import json
import os
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_client = None


def get_client():
    """Return a cached OpenAI-compatible client. Creates one on first call."""
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(
            api_key=os.environ["FAIRRIDE_API_KEY"],
            base_url=os.environ.get("FAIRRIDE_BASE_URL") or None,
        )
    return _client


def call_model(
    system_prompt: str,
    user_message: str,
    response_model: type[T],
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2000,
) -> T:
    """Call the model and parse the response into a Pydantic model.

    Uses JSON mode for structured output. The system prompt must instruct
    the model to return valid JSON matching the schema.

    Raises ModelCallError on parse failure or API error.
    """
    if os.environ.get("FAIRRIDE_STUB"):
        return _stub_response(system_prompt, user_message, response_model)

    from openai import APIError

    client = get_client()
    resolved_model = model or os.environ.get("FAIRRIDE_MODEL", "gpt-4o-mini")

    try:
        response = client.chat.completions.create(
            model=resolved_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
    except APIError as exc:
        raise ModelCallError(f"API call failed for {response_model.__name__}: {exc}") from exc

    raw = response.choices[0].message.content
    try:
        return response_model.model_validate_json(raw)
    except ValidationError as exc:
        raise ModelCallError(
            f"Model returned invalid JSON for {response_model.__name__}.\n"
            f"Raw (first 500 chars): {raw[:500]}\nError: {exc}"
        ) from exc


def _stub_response(system_prompt: str, user_message: str, response_model: type[T]) -> T:
    """Return a hand-written example instead of calling the model.

    Loads examples/agent_outputs.json and returns the matching example
    based on the role inferred from the system prompt.
    """
    from contracts import AdvocateResult, JudgeResult

    examples_path = Path(__file__).resolve().parents[1] / "examples" / "agent_outputs.json"
    examples = json.loads(examples_path.read_text())

    is_rebuttal = "FOLLOW-UP QUESTION" in system_prompt or "JUDGE'S QUESTION" in user_message

    if response_model is AdvocateResult:
        # Match the role declaration line, not the schema enum values
        if "You are the Rider Advocate" in system_prompt:
            key = "rider_advocate"
        elif "You are the Driver Advocate" in system_prompt:
            key = "driver_advocate"
        else:
            key = "rider_advocate"

        if is_rebuttal:
            return AdvocateResult(
                role=key,
                claims=[{
                    "statement": "The supplied records do not identify a designated physical pickup entrance beyond the lobby description and coordinates.",
                    "evidence_ids": ["TICKET-001", "TRIP-001"],
                    "policy_ids": ["POLICY-005"],
                }],
                counterpoints=[],
                unanswered_questions=["No record designates a specific entrance or meeting point."],
            )
        return AdvocateResult.model_validate(examples[key])

    if response_model is JudgeResult:
        if "second_pass" in user_message.lower() or "REBUTTAL RESPONSES" in user_message:
            return JudgeResult.model_validate(examples["judge_human_review"])
        return JudgeResult.model_validate(examples["judge_rebuttal"])

    raise ModelCallError(f"No stub available for {response_model.__name__}")


class ModelCallError(Exception):
    """Raised when a model response cannot be parsed or validated."""
