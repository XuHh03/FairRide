"""Ordered review with parallel advocates and at most one rebuttal round."""

import asyncio
from collections.abc import Callable
from time import perf_counter

from agents import AgentBackend, AgentCall, ModelAgentBackend
from checks import material_case_issues, validate_judge_decision, policy_outcome, escalation_issues, account_review_flags
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


async def run_review_async(
    case: dict, policy: dict, backend: AgentBackend | None = None,
    *, on_progress: Callable[[str], None] | None = None,
) -> WorkflowResult:
    """Use a supplied backend for examples/tests or the configured live model."""
    started = perf_counter()
    case_id = case.get("dispute_ticket", {}).get("dispute_id", "unknown")
    activity: list[ActivityEntry] = []
    issues: list[str] = []
    failure_category = None
    mandatory_escalation = False

    def progress(message: str) -> None:
        if on_progress is not None:
            on_progress(message)

    progress("Preparing evidence and checking policy")
    try:
        gates = escalation_issues(case, policy)
        if gates:
            progress("Human review required by policy")
            return WorkflowResult(
                case_id=case_id, status="human_review", activity_log=[ActivityEntry(
                    actor="system", event="policy_escalation",
                    output={"reasons": gates, "wall_duration_ms": round((perf_counter()-started)*1000)})],
                judge_result=_human_review("; ".join(gates), policy_ids=["POLICY-5.1", "POLICY-6.1", "POLICY-6.2"]),
                validation_issues=gates, mandatory_escalation=True, account_review_flags=account_review_flags(case))
        review = build_review_input(case, policy)
        agent = backend or ModelAgentBackend()
    except Exception as exc:
        reason = f"Review setup failed: {exc}"
        progress("Review setup failed; human review required")
        return WorkflowResult(
            case_id=case_id, status="human_review", activity_log=activity,
            judge_result=_human_review(reason), validation_issues=[reason],
            failure_category="setup",
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
                "citation_retries": call.citation_retries,
                "schema_retries": call.schema_retries,
                "citation_resolutions": call.citation_resolutions,
                "usage": {key: value for key, value in call.usage.items()
                          if key in ("prompt_tokens", "completion_tokens", "total_tokens")
                          and isinstance(value, int)},
            },
        ))
        name = "Rider Advocate" if role == "rider_advocate" else "Driver Advocate"
        progress(f"{name} finished its rebuttal" if question else f"{name} finished its evidence analysis")
        return result

    async def call_judge(
        rider: AdvocateResult, driver: AdvocateResult,
        rebuttals: list[AdvocateResult] | None = None,
        previous_assessment: JudgeResult | None = None,
        validation_feedback: dict | None = None,
    ) -> JudgeResult:
        progress("Judge is correcting its decision" if validation_feedback is not None else
                 "Judge is reviewing rebuttals" if rebuttals is not None else "Judge is reviewing initial arguments")
        started = perf_counter()
        if validation_feedback is not None:
            call = await agent.correct_judgment(review, rider, driver, validation_feedback,
                                               rebuttals, previous_assessment)
        else:
            call = await agent.judge(review, rider, driver, rebuttals, previous_assessment=previous_assessment)
        result = JudgeResult.model_validate(call.result)
        refs = validate_references(result, case, policy)
        if refs:
            raise ValueError("; ".join(refs))
        activity.append(ActivityEntry(
            actor="judge", event="decision_correction" if validation_feedback is not None else
            "final_review" if rebuttals is not None else "provisional_review",
            output={
                "result": result.model_dump(mode="json"),
                "duration_ms": round((perf_counter() - started) * 1000),
                "citation_retries": call.citation_retries,
                "schema_retries": call.schema_retries,
                "citation_resolutions": call.citation_resolutions,
                "usage": {key: value for key, value in call.usage.items()
                          if key in ("prompt_tokens", "completion_tokens", "total_tokens")
                          and isinstance(value, int)},
            },
        ))
        return result

    try:
        # These calls depend on the same immutable review, not on one another.
        progress("Rider and Driver Advocates are analyzing evidence")
        rider, driver = await asyncio.gather(
            call_advocate("rider_advocate"), call_advocate("driver_advocate")
        )
        rebuttals = None
        previous_assessment = None
        decision = await call_judge(rider, driver)
        if decision.action == "request_rebuttal":
            roles = list(dict.fromkeys(decision.rebuttal_roles))
            activity.append(ActivityEntry(
                actor="system", event="rebuttal_question",
                output={"question": decision.question, "roles": roles},
            ))
            progress("Advocates are answering the Judge's follow-up question")
            rebuttals = await asyncio.gather(
                *(call_advocate(role, decision.question) for role in roles)
            )
            previous_assessment = decision
            decision = await call_judge(rider, driver, rebuttals, previous_assessment=previous_assessment)
        progress("Finalizing: validating citations, policy and amounts")
        material_issues = material_case_issues(case, policy)
        corrector = getattr(agent, "correct_judgment", None)
        for attempt in range(2):
            gates = escalation_issues(case, policy, decision.confidence, final=decision.action == "final_ruling")
            if gates:
                mandatory_escalation = True
                issues.extend(gates + material_issues)
                if decision.action != "human_review":
                    decision = _human_review("; ".join(gates), decision.evidence_ids, decision.policy_ids)
                break
            decision_issues = validate_judge_decision(case, policy, decision)
            invalid = any(issue not in material_issues for issue in decision_issues)
            if (not invalid or material_issues or attempt == 1 or not callable(corrector)
                    or decision.action == "request_rebuttal"):
                issues.extend(decision_issues)
                if invalid:
                    failure_category = "validation"
                break
            ruling, refund, credit, basis = policy_outcome(case, policy)
            feedback = {
                "previous_response": decision.model_dump(mode="json"),
                "errors": decision_issues,
                "policy_requirements": {"ruling": ruling, "refund_cents": refund,
                    "goodwill_credit_cents": credit, "refund_basis": basis,
                    "required_precedent_id": "POLICY-7.3" if review.dispute_type == "no_show_charge" else "POLICY-7.1"},
            }
            activity.append(ActivityEntry(actor="system", event="decision_validation", output={"errors": decision_issues}))
            decision = await call_judge(rider, driver, rebuttals, previous_assessment, feedback)
            progress("Finalizing: validating the corrected decision")
        if failure_category == "validation":
            decision = _human_review("Judge response failed validation; no decision was issued.",
                                     decision.evidence_ids, decision.policy_ids)
        elif issues and decision.action != "human_review":
            decision = _human_review(
                "Material evidence or validation issues require human review.",
                decision.evidence_ids, decision.policy_ids,
            )
        status = "completed" if decision.action == "final_ruling" else "human_review"
        activity.append(ActivityEntry(
            actor="system", event="review_completed",
            output={"wall_duration_ms": round((perf_counter() - started) * 1000), "status": status},
        ))
        progress("Judge response failed validation" if failure_category else
                 "Review complete" if status == "completed" else "Review finished: human review required")
        return WorkflowResult(
            case_id=case_id, status=status, activity_log=activity,
            judge_result=decision, validation_issues=issues,
            failure_category=failure_category, mandatory_escalation=mandatory_escalation, account_review_flags=account_review_flags(case),
        )
    except Exception as exc:
        # A malformed model response or transport failure must not become a ruling.
        # isinstance (not type()) so ValidationError subclasses of ValueError are included.
        reason = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        progress("Agent review failed; human review required")
        issues.append(f"Agent review failed: {reason}")
        activity.append(ActivityEntry(
            actor="system", event="review_failed",
            output={"wall_duration_ms": round((perf_counter() - started) * 1000)},
        ))
        return WorkflowResult(
            case_id=case_id, status="human_review", activity_log=activity,
            judge_result=_human_review("Agent review could not be validated."),
            validation_issues=issues,
            failure_category="validation" if isinstance(exc, ValueError) else "model",
        )


def run_review(
    case: dict, policy: dict, backend: AgentBackend | None = None,
    *, on_progress: Callable[[str], None] | None = None,
) -> WorkflowResult:
    return asyncio.run(run_review_async(case, policy, backend, on_progress=on_progress))
