"""Evaluate imported cases against separate draft keys; never send keys to agents."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from time import perf_counter

from dotenv import load_dotenv

from case_data import policy_for_case
from case_import import parse_case_upload
from contracts import WorkflowResult
from evidence import build_review_input
from review_summary import build_review_report
from workflow import run_review


_RULINGS = {
    "uphold_charge": "uphold_charge", "reverse_charge": "reverse_charge",
    "partial_refund": "partial_refund", "no_action": "no_action",
    "conditional_uphold_charge": "uphold_charge",
    "conditional_refund_excess_distance_fare": "partial_refund",
}
_REFERRALS = {"human_review", "mandatory_human_review", "unresolved_goodwill_credit", "unresolved_traffic_justification"}
_ROLES = ("rider_advocate", "driver_advocate")


def dataset_inputs(cases_dir: Path, answer_key_dir: Path) -> list[tuple[Path, Path, dict]]:
    """Preflight every input and key filename before spending model calls."""
    if cases_dir.resolve() == answer_key_dir.resolve():
        raise ValueError("Cases and answer keys must be in separate folders")
    paths = sorted(cases_dir.glob("*.json"))
    if not paths:
        raise ValueError("No case JSON files found")
    inputs = []
    for path in paths:
        case = parse_case_upload(path.read_bytes())
        if case["dispute_ticket"]["dispute_id"] != path.stem:
            raise ValueError(f"Case ID must match its filename: {path.name}")
        key_path = answer_key_dir / path.name
        if not key_path.is_file():
            raise ValueError(f"Missing answer key: {path.name}")
        inputs.append((path, key_path, case))
    return inputs


def load_answer_key(path: Path, case_id: str) -> dict:
    """Read evaluation-only fields after the workflow has returned."""
    key = json.loads(path.read_text())
    _validate_key(key, case_id)
    return key


def _validate_key(key: dict, case_id: str) -> None:
    if not isinstance(key, dict) or key.get("case_id") != case_id:
        raise ValueError("Answer-key case_id does not match the input")
    label = key.get("expected_label")
    if label not in _RULINGS and label not in _REFERRALS:
        raise ValueError(f"Unsupported expected_label: {label}")
    if type(key.get("mandatory_human_review")) is not bool:
        raise ValueError("mandatory_human_review must be boolean")
    for name in ("expected_refund_cents", "expected_goodwill_credit_cents"):
        value = key[name]
        if value is None and (key["mandatory_human_review"] or label in _REFERRALS):
            continue
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be nonnegative integer cents")
    basis = key["refund_basis"]
    referral = key["mandatory_human_review"] or label in _REFERRALS
    if basis not in ("cancellation_fee", "excess_distance_fare") and not (referral and basis is None):
        raise ValueError("Unsupported answer-key refund_basis")
    threshold = key["confidence_requirement"]["policy_threshold"]
    if threshold is not None and (type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 <= threshold <= 1):
        raise ValueError("Invalid confidence policy_threshold")


def _retrieval_check(result: WorkflowResult, review) -> tuple[bool | None, list[str]]:
    if result.mandatory_escalation and any(e.event == "policy_escalation" for e in result.activity_log):
        return None, []  # Policy preflight deliberately skips all model calls.
    expected = {e.id for e in review.evidence if e.source != "dispute_ticket"}
    sources = {e.source for e in review.evidence if e.source != "dispute_ticket"}
    trip_id = next(e.data["trip_id"] for e in review.evidence if e.source == "dispute_ticket")
    issues = []
    for role in _ROLES:
        events = [e for e in result.activity_log if e.actor == role]
        requests = [e for e in events if e.event == "evidence_request"]
        seen = set()
        argued = False
        if not 1 <= len(requests) <= 3:
            issues.append(f"{role}: expected 1–3 retrieval calls, got {len(requests)}")
        for event in events:
            if event.event == "evidence_request":
                data = event.output
                if argued or data.get("error") or data.get("trip_id") != trip_id:
                    issues.append(f"{role}: invalid or late evidence retrieval")
                requested_sources = set(data.get("sources", []))
                returned = set(data.get("record_ids", []))
                wanted = {e.id for e in review.evidence if e.source in requested_sources}
                if not requested_sources or not requested_sources <= sources or returned != wanted:
                    issues.append(f"{role}: retrieved sources/records do not match the input")
                seen.update(returned)
            elif event.event == "initial_argument":
                argued = True
                if seen != expected:
                    issues.append(f"{role}: incomplete evidence before argument")
        if seen != expected:
            issues.append(f"{role}: incomplete source retrieval")
    return not issues, issues


def score_result(case: dict, policy: dict, result: WorkflowResult, key: dict) -> dict:
    """Compare to fixed external labels, without deriving the expected payout in code."""
    case_id = case["dispute_ticket"]["dispute_id"]
    _validate_key(key, case_id)
    review = build_review_input(case, policy)
    judge = result.judge_result
    final = result.status == "completed" and judge.action == "final_ruling"
    threshold = max(key["confidence_requirement"]["policy_threshold"] or 0, review.required_confidence)
    assessed_confidence = judge.confidence
    if assessed_confidence is None and not final:
        for event in reversed(result.activity_log):
            if event.actor == "judge" and event.output.get("result", {}).get("action") != "request_rebuttal":
                assessed_confidence = event.output.get("result", {}).get("confidence")
                break
    low_confidence = (assessed_confidence is not None and threshold > 0 and assessed_confidence < threshold)
    label = key["expected_label"]
    referral = key["mandatory_human_review"] or label in _REFERRALS
    conditional_referral = label.startswith("conditional_") and low_confidence and not final
    expected_referral = referral or conditional_referral
    expected_ruling = "human_review" if expected_referral else _RULINGS[label]
    actual_ruling = judge.ruling if final else judge.action
    checks = {
        "operational_success": result.failure_category is None,
        "case_id": result.case_id == case_id,
        "outcome": (result.status == "human_review" and judge.action == "human_review") if expected_referral
                   else (final and actual_ruling == expected_ruling),
        "amount_cents": None, "goodwill_credit_cents": None, "refund_basis": None,
        "confidence": None,
    }
    if final:
        proposed = judge.proposed_action
        checks.update(amount_cents=proposed is not None and proposed.amount_cents == key["expected_refund_cents"],
                      goodwill_credit_cents=proposed is not None and proposed.goodwill_credit_cents == key["expected_goodwill_credit_cents"],
                      refund_basis=proposed is not None and proposed.refund_basis == key["refund_basis"],
                      confidence=judge.confidence is not None and judge.confidence >= threshold)
    evidence_ids = {e.id for e in review.evidence}
    policy_ids = {clause.id for clause in review.policy.clauses}
    citation_issues = []
    pending = [judge.model_dump(mode="json")] + [e.output["result"] for e in result.activity_log
               if "result" in e.output and (e.actor == "judge" or e.event in ("initial_argument", "rebuttal", "argument_correction"))]
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, dict):
            for name, allowed in (("evidence_ids", evidence_ids), ("policy_ids", policy_ids)):
                for ref in item.get(name, []) or []:
                    if ref not in allowed:
                        citation_issues.append(f"Unknown {name}: {ref}")
            pending.extend(value for value in item.values() if isinstance(value, (dict, list)))
    checks["citations"] = not citation_issues
    checks["retrieval"], retrieval_issues = _retrieval_check(result, review)
    argument_issues = []
    if checks["retrieval"] is None:
        checks["argument_completion"] = None
    else:
        argument_issues = [f"{role}: missing validated initial argument" for role in _ROLES
                           if not any(e.actor == role and e.event == "initial_argument" for e in result.activity_log)]
        checks["argument_completion"] = not argument_issues
    failed_checks = [name for name, passed in checks.items() if passed is False]
    return {
        "verdict": "FAIL" if failed_checks else "PASS", "checks": checks,
        "failed_checks": failed_checks, "expected_ruling": expected_ruling,
        "actual_ruling": actual_ruling, "conditional_confidence_referral": conditional_referral,
        "assessed_confidence": assessed_confidence, "required_confidence": threshold,
        "oracle_status": key.get("answer_key_status", "unspecified"),
        "human_confirmation_required": key.get("human_confirmation_required_for_expected_answer"),
        "citation_issues": citation_issues, "retrieval_issues": retrieval_issues, "argument_issues": argument_issues,
    }


def run_dataset(cases_dir: Path, answer_key_dir: Path, output: Path, *, runs: int = 1) -> dict:
    if runs < 1:
        raise ValueError("runs must be at least 1")
    inputs = dataset_inputs(cases_dir, answer_key_dir)
    if any(output.resolve().is_relative_to(folder.resolve()) for folder in (cases_dir, answer_key_dir)):
        raise ValueError("Report output must be outside the case and answer-key folders")
    report = {
        "evaluation_version": "heldout-1.1", "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": os.getenv("FAIRRIDE_MODEL"), "gather_evidence": True,
        "argument_support_checker": os.getenv("FAIRRIDE_CHECK_ARGUMENT_SUPPORT") == "1",
        "oracle_notice": "Matches against draft keys are provisional. Independently review keys and explanations; prose is not semantically certified.",
        "cases": [], "summary": {},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    # Verify the destination before the first paid review, and leave a valid
    # checkpoint even if the process is interrupted during that review.
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    total = len(inputs) * runs
    for run in range(1, runs + 1):
        for path, key_path, case in inputs:
            case_id = case["dispute_ticket"]["dispute_id"]
            prefix = f"[{len(report['cases']) + 1}/{total}] {case_id} (run {run}/{runs})"
            print(f"{prefix}: Starting", flush=True)
            row = {"case_id": case_id, "run": run, "input_file": str(path), "verdict": "FAIL"}
            started = perf_counter()
            phase = "review"
            try:
                policy = policy_for_case(case)
                result = run_review(case, policy, None, gather_evidence=True,
                                    on_progress=lambda message: print(f"  {prefix}: {message}", flush=True))
                row["review"] = build_review_report(case, policy, result, "Live model")
                row["total_tokens"] = sum(e.output.get("usage", {}).get("total_tokens", 0) or 0 for e in result.activity_log)
                phase = "answer_key"
                key = load_answer_key(key_path, case_id)
                row.update(score_result(case, policy, result, key))
                row["expected"] = {name: key[name] for name in ("expected_label", "expected_refund_cents", "expected_goodwill_credit_cents", "refund_basis", "mandatory_human_review")}
            except Exception as exc:
                row.update(error_category=phase, error=f"{type(exc).__name__}: {exc}")
            row["wall_duration_ms"] = round((perf_counter() - started) * 1000)
            report["cases"].append(row)
            rows = report["cases"]
            report["summary"] = {
                "total": len(rows), "planned": total, "passed": sum(r["verdict"] == "PASS" for r in rows),
                "failed": sum(r["verdict"] == "FAIL" for r in rows),
                "operational_failures": sum(r.get("error_category") == "review" or r.get("checks", {}).get("operational_success") is False for r in rows),
                "final_rulings": sum(r.get("review", {}).get("workflow", {}).get("status") == "completed" for r in rows),
                "conditional_confidence_referrals": sum(r.get("conditional_confidence_referral", False) for r in rows),
                "total_tokens": sum(r.get("total_tokens", 0) for r in rows),
            }
            output.write_text(json.dumps(report, indent=2, ensure_ascii=False))
            detail = row.get("error") or ", ".join(row.get("failed_checks", [])) or "all applicable checks matched"
            print(f"{prefix}: {row['verdict']} — {detail} ({row['wall_duration_ms']} ms)", flush=True)
    print(f"Report: {output}\n{report['summary']['passed']}/{total} passed. Draft-key matches remain provisional.", flush=True)
    return report


def main(argv=None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-dir", required=True, type=Path)
    parser.add_argument("--answer-key-dir", required=True, type=Path)
    parser.add_argument("--live", action="store_true", help="Opt in to model calls using configured credentials")
    parser.add_argument("--dry-run", action="store_true", help="Check input files and key filenames without calls or reading key contents")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path("heldout_evaluation_results.json"))
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    if args.live == args.dry_run:
        parser.error("Choose either --dry-run or --live")
    try:
        inputs = dataset_inputs(args.cases_dir, args.answer_key_dir)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    if args.dry_run:
        print(f"{len(inputs)} input cases validated; key filenames paired. No answer-key contents read or model calls made.")
        return 0
    if not ((os.getenv("FAIRRIDE_API_KEY") or os.getenv("OPENAI_API_KEY")) and os.getenv("FAIRRIDE_MODEL")):
        parser.error("--live requires FAIRRIDE_API_KEY (or OPENAI_API_KEY) and FAIRRIDE_MODEL")
    try:
        report = run_dataset(args.cases_dir, args.answer_key_dir, args.output, runs=args.runs)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 1 if report["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
