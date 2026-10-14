"""Evaluation labels and batch metrics for FairRide no-show cases.

This module is the single source of truth for human-annotated expected
outcomes. Both the test suite and the CLI evaluation harness import from
here to avoid duplication.

Usage (CLI):
    python evaluation.py                  # example mode only
    python evaluation.py --live           # also run live mode
    python evaluation.py --live --runs 3  # 3 live runs per case
"""

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from case_data import load_case, load_policy, policy_for_case
from checks import charged_cents, material_case_issues, no_show_facts, validate_final_ruling, policy_outcome
from contracts import WorkflowResult
from evidence import build_evidence_index, validate_references
from workflow import run_review
from agents import ExampleAgentBackend

load_dotenv()


# ---------------------------------------------------------------------------
# Expected labels for no-show cases
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CaseLabel:
    """Human-annotated expected outcome for a single dispute case."""
    case_id: str
    expected_ruling: str          # uphold_charge | reverse_charge | partial_refund | human_review
    expected_waited_minutes: float
    expected_fee_eligible: bool
    rationale: str
    evidence_count: int
    notes: str = ""
    acceptable_alternatives: tuple = ()


LABELS: dict[str, CaseLabel] = {
    "DISP-002": CaseLabel(case_id="DISP-002", expected_ruling="uphold_charge",
        expected_waited_minutes=6.0, expected_fee_eligible=True,
        rationale="Supplied v2.1 policy and case conditions; see docs/POLICY_V2_1_SPEC.md.", evidence_count=26),
    "DISP-003": CaseLabel(case_id="DISP-003", expected_ruling="reverse_charge",
        expected_waited_minutes=4.0, expected_fee_eligible=False,
        rationale="Supplied v2.1 policy and case conditions; see docs/POLICY_V2_1_SPEC.md.", evidence_count=19),
    "DISP-004": CaseLabel(case_id="DISP-004", expected_ruling="uphold_charge",
        expected_waited_minutes=9.0, expected_fee_eligible=True,
        rationale="Supplied v2.1 policy and case conditions; see docs/POLICY_V2_1_SPEC.md.", evidence_count=26),
    "DISP-005": CaseLabel(case_id="DISP-005", expected_ruling="human_review",
        expected_waited_minutes=0, expected_fee_eligible=False,
        rationale="Supplied v2.1 policy and case conditions; see docs/POLICY_V2_1_SPEC.md.", evidence_count=32),
    "DISP-006": CaseLabel(case_id="DISP-006", expected_ruling="partial_refund",
        expected_waited_minutes=0, expected_fee_eligible=False,
        rationale="Supplied v2.1 policy and case conditions; see docs/POLICY_V2_1_SPEC.md.", evidence_count=26),
    "DISP-007": CaseLabel(case_id="DISP-007", expected_ruling="reverse_charge",
        expected_waited_minutes=5.0, expected_fee_eligible=False,
        rationale="Supplied v2.1 policy and case conditions; see docs/POLICY_V2_1_SPEC.md.", evidence_count=17),
    "DISP-008": CaseLabel(case_id="DISP-008", expected_ruling="human_review",
        expected_waited_minutes=0, expected_fee_eligible=False,
        rationale="Supplied v2.1 policy and case conditions; see docs/POLICY_V2_1_SPEC.md.", evidence_count=32),
    "DISP-009": CaseLabel(case_id="DISP-009", expected_ruling="human_review",
        expected_waited_minutes=0, expected_fee_eligible=False,
        rationale="Supplied v2.1 policy and case conditions; see docs/POLICY_V2_1_SPEC.md.", evidence_count=34),
    "DISP-010": CaseLabel(case_id="DISP-010", expected_ruling="partial_refund",
        expected_waited_minutes=0, expected_fee_eligible=False,
        rationale="Supplied v2.1 policy and case conditions; see docs/POLICY_V2_1_SPEC.md.", evidence_count=20),
    "DISP-011": CaseLabel(case_id="DISP-011", expected_ruling="uphold_charge",
        expected_waited_minutes=0, expected_fee_eligible=False,
        rationale="Supplied v2.1 policy and case conditions; see docs/POLICY_V2_1_SPEC.md.", evidence_count=20),
    "DISP-012": CaseLabel(case_id="DISP-012", expected_ruling="human_review",
        expected_waited_minutes=0, expected_fee_eligible=False,
        rationale="Supplied v2.1 policy and case conditions; see docs/POLICY_V2_1_SPEC.md.", evidence_count=21),
}


# ---------------------------------------------------------------------------
# Metrics collection
# ---------------------------------------------------------------------------

@dataclass
class CaseMetrics:
    """Collected metrics for a single case run."""
    case_id: str
    mode: str                 # "example" or "live"
    run: int                  # run number (1-based)
    status: str               # "completed" or "human_review"
    ruling: str | None        # actual ruling (or action if not final_ruling)
    expected_ruling: str
    ruling_match: bool       # correct final ruling AND amount; never an escalation
    amount_cents: int | None
    amount_correct: bool | None  # None when no final amount exists
    confidence: float | None
    validation_issues: list[str]
    citation_error_count: int
    rebuttal_used: bool
    wall_duration_ms: float
    advocate_tokens: int
    judge_tokens: int
    total_tokens: int
    judge_explanation: str
    category: str             # correct/incorrect ruling, appropriate/unnecessary escalation, operational_failure
    failure_category: str | None = None
    error: str | None = None


def _extract_token_usage(activity_log: list) -> tuple[int, int, int]:
    """Sum token usage from advocate and judge entries."""
    adv_tokens = 0
    judge_tokens = 0
    for entry in activity_log:
        usage = entry.output.get("usage", {})
        tokens = usage.get("total_tokens", 0) or 0
        if entry.actor in ("rider_advocate", "driver_advocate"):
            adv_tokens += tokens
        elif entry.actor == "judge":
            judge_tokens += tokens
    return adv_tokens, judge_tokens, adv_tokens + judge_tokens


def _extract_wall_duration(activity_log: list) -> float:
    """Get wall-clock duration from the review_completed/review_failed entry."""
    for entry in activity_log:
        if entry.event in ("review_completed", "review_failed"):
            return entry.output.get("wall_duration_ms", 0)
    return 0


def _check_rebuttal_used(activity_log: list) -> bool:
    """Whether a rebuttal round was triggered."""
    return any(entry.event == "rebuttal" for entry in activity_log)


def _count_citation_errors(issues: list[str]) -> int:
    """Count citation-related validation issues."""
    keywords = ("Unknown evidence ID", "Unknown policy ID", "citation")
    return sum(1 for issue in issues if any(kw in issue for kw in keywords))


def _policy_for_case(case: dict) -> dict:
    """Load the appropriate policy based on dispute type."""
    return policy_for_case(case)


def run_single_case(
    case_id: str,
    mode: str,
    policy: dict | None = None,
    run: int = 1,
) -> CaseMetrics:
    """Run one case and collect metrics."""
    case = load_case(case_id)
    label = LABELS[case_id]
    if policy is None:
        policy = _policy_for_case(case)

    if mode == "example":
        backend = ExampleAgentBackend()
    else:
        backend = None  # ModelAgentBackend (live)

    try:
        result = run_review(case, policy, backend)
    except Exception as exc:
        return CaseMetrics(
            case_id=case_id, mode=mode, run=run,
            status="error", ruling=None,
            expected_ruling=label.expected_ruling,
            ruling_match=False, amount_cents=None,
            amount_correct=None, confidence=None,
            validation_issues=[f"Exception: {exc}"],
            citation_error_count=0, rebuttal_used=False,
            wall_duration_ms=0, advocate_tokens=0,
            judge_tokens=0, total_tokens=0,
            judge_explanation="", category="operational_failure",
            failure_category="setup", error=str(exc),
        )

    judge = result.judge_result
    ruling = judge.ruling if judge.action == "final_ruling" else judge.action

    # Ruling match check
    acceptable = {label.expected_ruling} | set(label.acceptable_alternatives)
    ruling_match = (result.failure_category is None and result.status == "completed"
                    and judge.action == "final_ruling" and ruling in acceptable)

    # Amount correctness
    amount = judge.proposed_action.amount_cents if judge.proposed_action else None
    charge = charged_cents(case)
    if ruling in ("uphold_charge", "no_action"):
        amount_correct = amount == 0
    elif ruling == "reverse_charge":
        amount_correct = amount == charge
    elif ruling == "partial_refund":
        amount_correct = amount == policy_outcome(case, policy)[1]
    else:
        amount_correct = None  # No final ruling means no amount to score.

    if result.failure_category is not None:
        category = "operational_failure"
        ruling_match = False
        amount_correct = None
    elif judge.action == "final_ruling" and result.status == "completed":
        ruling_match = ruling_match and amount_correct is True
        category = "correct_ruling" if ruling_match else "incorrect_ruling"
    else:
        category = ("appropriate_escalation" if (label.expected_ruling == "human_review" or result.mandatory_escalation)
                    else "unnecessary_escalation")
        ruling_match = False

    # Tokens and timing
    adv_tokens, judge_tokens, total_tokens = _extract_token_usage(result.activity_log)
    wall_ms = _extract_wall_duration(result.activity_log)
    rebuttal_used = _check_rebuttal_used(result.activity_log)
    citation_errors = _count_citation_errors(result.validation_issues)

    return CaseMetrics(
        case_id=case_id, mode=mode, run=run,
        status=result.status,
        ruling=ruling,
        expected_ruling=label.expected_ruling,
        ruling_match=ruling_match,
        amount_cents=amount,
        amount_correct=amount_correct,
        confidence=judge.confidence,
        validation_issues=result.validation_issues,
        citation_error_count=citation_errors,
        rebuttal_used=rebuttal_used,
        wall_duration_ms=wall_ms,
        advocate_tokens=adv_tokens,
        judge_tokens=judge_tokens,
        total_tokens=total_tokens,
        judge_explanation=judge.explanation,
        category=category, failure_category=result.failure_category,
        error="; ".join(result.validation_issues) if result.failure_category else None,
    )


# ---------------------------------------------------------------------------
# Summary aggregation
# ---------------------------------------------------------------------------

@dataclass
class ModeSummary:
    """Rates use different denominators; unavailable accuracy serializes as null."""
    mode: str
    total_cases: int
    final_rulings: int
    ruling_matches: int
    ruling_accuracy: float | None
    autonomous_resolution_rate: float
    clear_cases: int
    unnecessary_escalations: int
    unnecessary_escalation_rate: float | None
    appropriate_escalations: int
    operational_failures: int
    operational_failure_rate: float
    abstentions: int
    abstention_rate: float
    amount_errors: int
    citation_errors: int
    rebuttals_used: int
    avg_wall_ms: float
    total_tokens: int
    avg_confidence: float | None


def summarize(metrics: list[CaseMetrics], mode: str) -> ModeSummary:
    n = len(metrics)
    finals = sum(m.category in ("correct_ruling", "incorrect_ruling") for m in metrics)
    matches = sum(m.ruling_match for m in metrics)
    clear = sum(m.expected_ruling != "human_review" for m in metrics)
    unnecessary = sum(m.category == "unnecessary_escalation" for m in metrics)
    appropriate = sum(m.category == "appropriate_escalation" for m in metrics)
    failures = sum(m.category == "operational_failure" for m in metrics)
    abstentions = unnecessary + appropriate
    confidences = [m.confidence for m in metrics if m.confidence is not None]
    return ModeSummary(
        mode=mode, total_cases=n, final_rulings=finals, ruling_matches=matches,
        ruling_accuracy=matches / finals if finals else None,
        autonomous_resolution_rate=finals / n if n else 0,
        clear_cases=clear, unnecessary_escalations=unnecessary,
        unnecessary_escalation_rate=unnecessary / clear if clear else None,
        appropriate_escalations=appropriate,
        operational_failures=failures, operational_failure_rate=failures / n if n else 0,
        abstentions=abstentions, abstention_rate=abstentions / n if n else 0,
        amount_errors=sum(m.amount_correct is False for m in metrics),
        citation_errors=sum(m.citation_error_count for m in metrics),
        rebuttals_used=sum(m.rebuttal_used for m in metrics),
        avg_wall_ms=sum(m.wall_duration_ms for m in metrics) / n if n else 0,
        total_tokens=sum(m.total_tokens for m in metrics),
        avg_confidence=sum(confidences) / len(confidences) if confidences else None,
    )


# ---------------------------------------------------------------------------
# Console report
# ---------------------------------------------------------------------------

def _fmt_pct(val: float | None) -> str:
    return "N/A" if val is None else f"{val * 100:.0f}%"


def print_report(metrics: list[CaseMetrics], summaries: list[ModeSummary]) -> None:
    """Print a human-readable report to stdout."""
    print()
    print("=" * 100)
    print("  FairRide Evaluation Report")
    print("=" * 100)
    print()

    # Per-case detail table
    print("  Per-Case Results")
    print("-" * 100)
    header = (
        f"  {'Case':<10} {'Mode':<8} {'Run':<4} "
        f"{'Ruling':<16} {'Expected':<16} {'Match':<6} "
        f"{'Amount':<8} {'Conf':<6} {'Wall ms':<10} {'Tokens':<8} {'Rebut':<6} {'Category'}"
    )
    print(header)
    print("-" * 100)

    for m in metrics:
        ruling_str = (m.ruling or "None")[:14]
        expected_str = m.expected_ruling[:14]
        amount_str = str(m.amount_cents) if m.amount_cents is not None else "-"
        conf_str = f"{m.confidence:.2f}" if m.confidence is not None else "-"
        match_str = "Y" if m.ruling_match else "-" if "escalation" in m.category else "N"
        rebut_str = "Y" if m.rebuttal_used else "N"
        print(
            f"  {m.case_id:<10} {m.mode:<8} {m.run:<4} "
            f"{ruling_str:<16} {expected_str:<16} {match_str:<6} "
            f"{amount_str:<8} {conf_str:<6} {m.wall_duration_ms:<10.0f} "
            f"{m.total_tokens:<8} {rebut_str:<6} {m.category}"
        )

    print()
    print("  Mode Summaries")
    print("-" * 100)
    for s in summaries:
        conf_str = f"{s.avg_confidence:.2f}" if s.avg_confidence is not None else "-"
        print(f"  [{s.mode}]")
        print(f"    Cases:              {s.total_cases}")
        print(f"    Autonomous resolution: {_fmt_pct(s.autonomous_resolution_rate)} ({s.final_rulings}/{s.total_cases})")
        print(f"    Ruling accuracy:    {_fmt_pct(s.ruling_accuracy)} ({s.ruling_matches}/{s.final_rulings})")
        print(f"    Unnecessary escalation: {_fmt_pct(s.unnecessary_escalation_rate)} ({s.unnecessary_escalations}/{s.clear_cases} clear cases)")
        print(f"    Operational failures: {_fmt_pct(s.operational_failure_rate)} ({s.operational_failures}/{s.total_cases})")
        print(f"    Appropriate escalations: {s.appropriate_escalations}")
        print(f"    Abstention rate:    {_fmt_pct(s.abstention_rate)} ({s.abstentions}/{s.total_cases})")
        print(f"    Amount errors:      {s.amount_errors}")
        print(f"    Citation errors:    {s.citation_errors}")
        print(f"    Rebuttals used:     {s.rebuttals_used}")
        print(f"    Avg wall time:      {s.avg_wall_ms:.0f} ms")
        print(f"    Total tokens:       {s.total_tokens}")
        print(f"    Avg confidence:     {conf_str}")
        print()

    # Validation issues detail
    issues_metrics = [m for m in metrics if m.validation_issues]
    if issues_metrics:
        print("  Validation Issues Detail")
        print("-" * 100)
        for m in issues_metrics:
            print(f"  {m.case_id} ({m.mode}, run {m.run}):")
            for issue in m.validation_issues:
                print(f"    - {issue}")
        print()

    print("=" * 100)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch-evaluate FairRide dispute cases.",
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Also run live mode (requires FAIRRIDE_API_KEY).",
    )
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Number of live runs per case (default: 1).",
    )
    parser.add_argument(
        "--output", type=str, default="evaluation_results.json",
        help="Output JSON file path (default: evaluation_results.json).",
    )
    args = parser.parse_args()

    all_metrics: list[CaseMetrics] = []
    summaries: list[ModeSummary] = []

    # --- Example mode ---
    print("Running example mode...")
    example_metrics: list[CaseMetrics] = []
    for case_id in LABELS:
        m = run_single_case(case_id, "example", policy=None, run=1)
        example_metrics.append(m)
        status_icon = m.category
        print(f"  {case_id}: {m.ruling} (expected {m.expected_ruling}) [{status_icon}]")

    all_metrics.extend(example_metrics)
    summaries.append(summarize(example_metrics, "example"))

    # --- Live mode ---
    if args.live:
        api_key = os.getenv("FAIRRIDE_API_KEY") or os.getenv("OPENAI_API_KEY")
        model = os.getenv("FAIRRIDE_MODEL")
        if not api_key or not model:
            print("ERROR: --live requires FAIRRIDE_API_KEY and FAIRRIDE_MODEL in .env")
            sys.exit(1)

        for run_num in range(1, args.runs + 1):
            print(f"\nRunning live mode (run {run_num}/{args.runs})...")
            live_metrics: list[CaseMetrics] = []
            for case_id in LABELS:
                m = run_single_case(case_id, "live", policy=None, run=run_num)
                live_metrics.append(m)
                status_icon = m.category
                print(f"  {case_id}: {m.ruling} (expected {m.expected_ruling}) [{status_icon}] "
                      f"({m.wall_duration_ms:.0f}ms, {m.total_tokens} tokens)")

            all_metrics.extend(live_metrics)

        # Summarize all live runs together
        live_all = [m for m in all_metrics if m.mode == "live"]
        summaries.append(summarize(live_all, "live"))

    # --- Report ---
    print_report(all_metrics, summaries)

    # --- JSON output ---
    output_path = Path(args.output)
    report_data = {
        "evaluation_version": "2.0",
        "cases": [asdict(m) for m in all_metrics],
        "summaries": [asdict(s) for s in summaries],
    }
    output_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False))
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
