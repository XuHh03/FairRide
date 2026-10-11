"""Judge prompt and model call."""

import json
import os

from agents.client import call_model
from contracts import AdvocateResult, JudgeResult, ReviewInput

_SCHEMA = JudgeResult.model_json_schema()

_JUDGE_SYSTEM = """\
You are the Judge in a ride-hailing dispute resolution system for Ryde Singapore.

YOUR ROLE
Weigh the evidence from both advocates, apply the policy, and issue one of three actions.

ACTIONS
1. "request_rebuttal" — You need a specific piece of evidence clarified. Ask one precise question directed to one or both advocates. This may happen at most once per case.
2. "final_ruling" — The evidence is sufficient. Issue a ruling and a proposed action.
3. "human_review" — Material facts remain unresolved. Refer the case for human review.

RULES
1. You see the original evidence, derived facts, policy, and both advocates' arguments.
2. Every ruling or explanation must cite at least one evidence_id or policy_id.
3. If the designated pickup entrance, rider location, or any material fact is not established by the records, do not assume it. Either request a rebuttal or refer to human review.
4. If two records conflict (e.g., an event description vs. a policy threshold), acknowledge the conflict in your explanation and cite both.
5. Do not use rider or driver profiles (ratings, dispute history, fraud flags) as the basis for your ruling.
6. Do not invent evidence IDs.
7. "proposed_action.amount_cents" is the refund to the rider in SGD cents (integer), not the original charge.
   - "uphold_charge" or "no_action": amount_cents must be 0.
   - "reverse_charge": amount_cents must equal the charged amount.
   - "partial_refund": amount_cents must be positive and less than the charged amount.
   Python will verify these; do not set them arbitrarily.
8. "confidence" (0.0 to 1.0) is your self-assessed certainty. It is displayed as context and cannot override evidence or policy checks.

OUTPUT
Return a JSON object matching this schema:
{schema}

If you are requesting a rebuttal, set action="request_rebuttal", provide a "question" and "rebuttal_roles", and leave ruling/proposed_action empty.
If you are issuing a final ruling, set action="final_ruling", provide "ruling" and "proposed_action", and leave question/rebuttal_roles empty.
If you are referring to human review, set action="human_review", provide an "explanation", and leave ruling/proposed_action/question/rebuttal_roles empty.
"""


def _build_judge_user_message(
    review: ReviewInput,
    rider: AdvocateResult,
    driver: AdvocateResult,
    rebuttals: list[AdvocateResult] | None,
) -> str:
    parts = [
        f"Case: {review.case_id}",
        f"Dispute type: {review.dispute_type}",
        "",
        "EVIDENCE AND DERIVED FACTS:",
        review.model_dump_json(indent=2),
        "",
        "RIDER ADVOCATE ARGUMENT:",
        rider.model_dump_json(indent=2),
        "",
        "DRIVER ADVOCATE ARGUMENT:",
        driver.model_dump_json(indent=2),
    ]
    if rebuttals:
        parts.extend(["", "REBUTTAL RESPONSES:"])
        for r in rebuttals:
            parts.append(r.model_dump_json(indent=2))
    parts.extend(["", "Return a JSON object matching the JudgeResult schema."])
    return "\n".join(parts)


def judge(
    review: ReviewInput,
    rider_argument: AdvocateResult,
    driver_argument: AdvocateResult,
    rebuttals: list[AdvocateResult] | None = None,
) -> JudgeResult:
    """Return a ruling, a specific evidence request, or human review."""
    system = _JUDGE_SYSTEM.format(schema=json.dumps(_SCHEMA, indent=2))
    user = _build_judge_user_message(review, rider_argument, driver_argument, rebuttals)
    model = os.environ.get("FAIRRIDE_JUDGE_MODEL") or None
    return call_model(system, user, JudgeResult, model=model)
