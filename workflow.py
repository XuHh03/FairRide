"""Ordered review with parallel advocates and at most one rebuttal round."""

import asyncio
from time import perf_counter

from agents import AgentBackend, AgentCall, ModelAgentBackend
from checks import material_case_issues, validate_final_ruling
from contracts import ActivityEntry, AdvocateResult, JudgeResult, Role, WorkflowResult
from evidence import build_review_input, validate_references


def _human_review(
    reason: str, evidence_ids: list[str] | None = None,
    policy_ids: list[str] | None = None,
) -> JudgeResult:
    return JudgeResult(
        action="human_review", explanation=reason,
        evidence_ids=evidence_ids or [], policy_ids=policy_ids or [],
    )


async def run_review_async(case: dict, policy: dict, backend: AgentBackend | None = None) -> WorkflowResult:
    """Use a supplied backend for examples/tests or the configured live model."""
    started = perf_counter()
    case_id = case.get("dispute_ticket", {}).get("dispute_id", "unknown")
    activity: list[ActivityEntry] = []
    issues: list[str] = []
    try:
        review = build_review_input(case, policy)
        agent = backend or ModelAgentBackend()
    except Exception as exc:
        reason = f"Review setup failed: {exc}"
        return WorkflowResult(
            case_id=case_id, status="human_review", activity_log=activity,
            judge_result=_human_review(reason), validation_issues=[reason],
        )

    async def call_advocate(role: Role, question: str | None = None) -> AdvocateResult:
        started = perf_counter()
        call: AgentCall[AdvocateResult] = await agent.advocate(review, role, question)
        result = AdvocateResult.model_validate(call.result)
        if result.role != role:
            raise ValueError(f"{role} returned the wrong role")
        refs = validate_references(result, case, policy)
        if refs:
            raise ValueError("; ".join(refs))
        activity.append(ActivityEntry(
            actor=role, event="rebuttal" if question else "initial_argument",
            output={
                "result": result.model_dump(mode="json"),
                "duration_ms": round((perf_counter() - started) * 1000),
                "usage": {key: value for key, value in call.usage.items()
                          if key in ("prompt_tokens", "completion_tokens", "total_tokens")
                          and isinstance(value, int)},
            },
        ))
        return result

    async def call_judge(
        rider: AdvocateResult, driver: AdvocateResult,
        rebuttals: list[AdvocateResult] | None = None,
    ) -> JudgeResult:
        started = perf_counter()
        call: AgentCall[JudgeResult] = await agent.judge(review, rider, driver, rebuttals)
        result = JudgeResult.model_validate(call.result)
        refs = validate_references(result, case, policy)
        if refs:
            raise ValueError("; ".join(refs))
        activity.append(ActivityEntry(
            actor="judge", event="final_review" if rebuttals is not None else "provisional_review",
            output={
                "result": result.model_dump(mode="json"),
                "duration_ms": round((perf_counter() - started) * 1000),
                "usage": {key: value for key, value in call.usage.items()
                          if key in ("prompt_tokens", "completion_tokens", "total_tokens")
                          and isinstance(value, int)},
            },
        ))
        return result

    try:
        # These calls depend on the same immutable review, not on one another.
        rider, driver = await asyncio.gather(
            call_advocate("rider_advocate"), call_advocate("driver_advocate")
        )
        decision = await call_judge(rider, driver)
        if decision.action == "request_rebuttal":
            roles = list(dict.fromkeys(decision.rebuttal_roles))
            activity.append(ActivityEntry(
                actor="system", event="rebuttal_question",
                output={"question": decision.question, "roles": roles},
            ))
            rebuttals = await asyncio.gather(
                *(call_advocate(role, decision.question) for role in roles)
            )
            decision = await call_judge(rider, driver, rebuttals)
            if decision.action == "request_rebuttal":
                issues.append("Judge requested a second rebuttal round")
        if decision.action == "final_ruling":
            issues.extend(validate_final_ruling(case, policy, decision))
        else:
            issues.extend(material_case_issues(case, policy))
        if issues and decision.action != "human_review":
            decision = _human_review(
                "Material evidence or validation issues require human review.",
                decision.evidence_ids, decision.policy_ids,
            )
        status = "completed" if decision.action == "final_ruling" else "human_review"
        activity.append(ActivityEntry(
            actor="system", event="review_completed",
            output={"wall_duration_ms": round((perf_counter() - started) * 1000), "status": status},
        ))
        return WorkflowResult(
            case_id=case_id, status=status, activity_log=activity,
            judge_result=decision, validation_issues=issues,
        )
    except Exception as exc:
        # A malformed model response or transport failure must not become a ruling.
        reason = str(exc) if type(exc) in (ValueError, RuntimeError) else type(exc).__name__
        issues.append(f"Agent review failed: {reason}")
        activity.append(ActivityEntry(
            actor="system", event="review_failed",
            output={"wall_duration_ms": round((perf_counter() - started) * 1000)},
        ))
        return WorkflowResult(
            case_id=case_id, status="human_review", activity_log=activity,
            judge_result=_human_review("Agent review could not be validated."),
            validation_issues=issues,
        )


def run_review(case: dict, policy: dict, backend: AgentBackend | None = None) -> WorkflowResult:
    return asyncio.run(run_review_async(case, policy, backend))
