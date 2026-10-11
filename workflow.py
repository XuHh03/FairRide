"""Control the order of agent calls and limit review to one rebuttal round."""

from contracts import ActivityEntry, JudgeResult, WorkflowResult
from evidence import build_review_input, validate_references
from agents import rider_advocate, driver_advocate, judge
from agents.client import ModelCallError
from checks import validate_amounts


def run_review(case: dict, policy: dict) -> WorkflowResult:
    """Run the full agent pipeline for one case.

    Steps:
    1. Prepare ReviewInput (evidence + policy + derived facts).
    2. Call both advocates.
    3. Validate advocate citations.
    4. Call the Judge.
    5. If Judge requests rebuttal: route question, collect responses, call Judge again.
    6. Validate the final result: citations + amounts.
    7. Build WorkflowResult with activity log.
    """
    log: list[ActivityEntry] = []
    issues: list[str] = []

    # 1. Prepare input
    review = build_review_input(case, policy)
    fact_ids = {f.id for f in review.facts}
    log.append(ActivityEntry(
        actor="system", event="review_prepared",
        output={"case_id": review.case_id,
                "evidence_count": len(review.evidence),
                "fact_count": len(review.facts)},
    ))

    # 2. Call advocates
    rider = _call_advocate(rider_advocate, review, case, policy,
                           "rider_advocate", log, issues, fact_ids=fact_ids)
    if rider is None:
        return _human_review_result(review.case_id, log, issues)

    driver = _call_advocate(driver_advocate, review, case, policy,
                             "driver_advocate", log, issues, fact_ids=fact_ids)
    if driver is None:
        return _human_review_result(review.case_id, log, issues)

    # 4. Call Judge (pass 1)
    result = _call_judge(review, rider, driver, None, case, policy, log, issues,
                         fact_ids=fact_ids)
    if result is None:
        return _human_review_result(review.case_id, log, issues)

    # 5. Rebuttal (at most once)
    if result.action == "request_rebuttal":
        rebuttals: list = []
        for role in result.rebuttal_roles:
            fn = rider_advocate if role == "rider_advocate" else driver_advocate
            rebuttal = _call_advocate(fn, review, case, policy, role, log, issues,
                                      question=result.question, fact_ids=fact_ids)
            if rebuttal is not None:
                rebuttals.append(rebuttal)

        # Judge pass 2
        result = _call_judge(review, rider, driver, rebuttals, case, policy, log, issues,
                             fact_ids=fact_ids)
        if result is None:
            return _human_review_result(review.case_id, log, issues)

        # Enforce one-round limit
        if result.action == "request_rebuttal":
            issues.append("Rebuttal limit reached; second request overridden to human_review.")
            log.append(ActivityEntry(
                actor="system", event="rebuttal_limit_enforced", output={},
            ))
            result = JudgeResult(
                action="human_review",
                explanation=result.explanation + " (Rebuttal limit reached.)",
                evidence_ids=result.evidence_ids,
                policy_ids=result.policy_ids,
            )

    # 6. Final amount validation
    issues += validate_amounts(result, policy)

    # 7. Build result
    status = "human_review" if result.action == "human_review" or issues else "completed"
    return WorkflowResult(
        case_id=review.case_id,
        status=status,
        activity_log=log,
        judge_result=result,
        validation_issues=issues,
    )


def _call_advocate(fn, review, case, policy, role, log, issues, question=None,
                   fact_ids=None):
    """Call an advocate, log the result, and validate citations.

    Returns the AdvocateResult, or None if the call failed.
    """
    event = "rebuttal_response" if question else "initial_argument"
    try:
        result = fn(review, question=question)
    except ModelCallError as exc:
        issues.append(f"{role} call failed: {exc}")
        log.append(ActivityEntry(actor=role, event=f"{event}_failed",
                                 output={"error": str(exc)}))
        return None

    log.append(ActivityEntry(actor=role, event=event,
                             output=result.model_dump(mode="json")))
    issues += validate_references(result, case, policy, fact_ids=fact_ids)
    return result


def _call_judge(review, rider, driver, rebuttals, case, policy, log, issues,
                fact_ids=None):
    """Call the Judge, log the result, and validate citations.

    Returns the JudgeResult, or None if the call failed.
    """
    event = "second_pass" if rebuttals is not None else "first_pass"
    try:
        result = judge(review, rider, driver, rebuttals=rebuttals)
    except ModelCallError as exc:
        issues.append(f"Judge {event} failed: {exc}")
        log.append(ActivityEntry(actor="judge", event=f"{event}_failed",
                                 output={"error": str(exc)}))
        return None

    log.append(ActivityEntry(actor="judge", event=event,
                             output=result.model_dump(mode="json")))
    issues += validate_references(result, case, policy, fact_ids=fact_ids)
    return result


def _human_review_result(case_id, log, issues):
    """Build a human-review WorkflowResult for error/failure cases."""
    return WorkflowResult(
        case_id=case_id,
        status="human_review",
        activity_log=log,
        judge_result=JudgeResult(
            action="human_review",
            explanation="Review could not complete due to errors or missing model calls.",
        ),
        validation_issues=issues,
    )
