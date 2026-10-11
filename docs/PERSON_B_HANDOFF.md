# Person B handoff — shared foundation v1.0

Updated 5 October 2026. This began as the shared-foundation handoff and now includes the implemented no-show review path. See `progress.md` for the latest status.

## Implemented by Person A's shared-foundation task

- `contracts.py`: Pydantic v2 input/output schemas, unknown-field rejection, cited claims, Judge action constraints, integer refund cents, and contract version `1.0`.
- `evidence.py`: evidence lookup, policy lookup, agent-input preparation, and citation existence checks.
- `cases/DISP-002.json`: explicit, stable IDs on the ticket, trip, GPS, chats, and app events. Original record values are retained; profile history remains in the raw fixture but is excluded from agent input.
- `policies/sample_no_show.json`: version `1.0`, six individually identified sample clauses, and explicit policy assumptions.
- `checks.py`: waiting-time calculation now follows `wait_start_event`. The fixture still gives eight minutes with the arrival-based rule.
- `examples/agent_outputs.json`: hand-written examples of both advocates and all three Judge actions. These are interface examples, not model results or evaluation labels.
- `agents.py` and `workflow.py`: the original typed signatures now have live and example backends plus a one-round controller.
- `tests/test_shared_contract.py`: executable shared-interface checks, alongside existing no-show tests.

## Current implementation limit

The model client, three role calls, rebuttal execution, no-show final amount checks, and result UI are implemented. The hand-written example walkthrough has been verified; the live endpoint has only been tested with a mocked HTTP response. No real provider call, route-deviation facts, multi-case evaluation, or payment execution has been verified.

## Public interfaces

| Function | Input | Output |
|---|---|---|
| `case_data.load_case(case_id)` | `"DISP-002"` | Raw case dictionary |
| `case_data.load_policy(policy_id)` | `"sample_no_show"` | Raw policy dictionary |
| `evidence.build_evidence_index(case)` | Raw case | ID → `EvidenceRecord` |
| `evidence.build_policy_index(policy)` | Raw policy | Clause ID → `PolicyClause` |
| `evidence.build_review_input(case, policy)` | Raw case and policy | `ReviewInput` |
| `evidence.validate_references(result, case, policy)` | Parsed advocate/Judge result and raw records | Error strings; empty list means all cited IDs exist |
| `agents.rider_advocate(review)` | `ReviewInput` | `AdvocateResult` from configured live model |
| `agents.driver_advocate(review)` | `ReviewInput` | `AdvocateResult` from configured live model |
| `agents.judge(review, rider_argument, driver_argument, rebuttals=None)` | Shared typed input and outputs | `JudgeResult` from configured live model |
| `workflow.run_review(case, policy, backend=None)` | Raw case and policy; optional injectable backend | Validated `WorkflowResult` |

To split file ownership later, move the advocate functions to `agents/advocates.py` and Judge to `agents/judge.py`, replacing the current `agents.py`. Keep these signatures and imports compatible. Do not create both the same-named module and package as competing implementations.

## Runnable integration example — no API key needed

Run from the repository root after installing `requirements.txt`:

```python
import json
from pathlib import Path

from case_data import load_case, load_policy
from contracts import AdvocateResult, JudgeResult
from evidence import build_review_input, validate_references

case = load_case("DISP-002")
policy = load_policy("sample_no_show")
review = build_review_input(case, policy)
examples = json.loads(Path("examples/agent_outputs.json").read_text())
rider = AdvocateResult.model_validate(examples["rider_advocate"])
driver = AdvocateResult.model_validate(examples["driver_advocate"])
judge_output = JudgeResult.model_validate(examples["judge_rebuttal"])
for result in (rider, driver, judge_output):
    assert validate_references(result, case, policy) == []
print(review.case_id, judge_output.action)
```

Use `review.model_dump(mode="json")` for model input. Parse a JSON string with `AdvocateResult.model_validate_json(text)` or `JudgeResult.model_validate_json(text)`. Use `model_json_schema()` when your model provider supports a JSON schema response format. Validate citations after parsing every response, including rebuttals.

## Evidence conventions

- IDs are case-local: `TICKET-001`, `TRIP-001`, `GPS-001`–`GPS-008`, `CHAT-001`–`CHAT-006`, and `EVENT-001`–`EVENT-010` in this fixture.
- Every source record carries its own explicit ID. Never regenerate IDs from array positions after edits. New records receive new unused IDs; reordered records keep their IDs.
- Policy IDs are `POLICY-001`–`POLICY-006` within the selected policy version. Store the case ID and policy version with results.
- `EvidenceRecord.source` identifies the original section; `.data` contains its original fields without the ID wrapper. For example, `build_evidence_index(case)["GPS-005"]` resolves the 08:43 GPS record.
- `FACT-001`–`FACT-003` are derived facts, not raw-source IDs. They retain formulas and source/policy citations. Cite those original IDs in claims, not a `FACT-*` ID.
- `validate_references` checks existence only. It does not prove that a cited record supports a statement, enforce a policy, or establish refund eligibility.
- Do not send the original sample document or expected outcomes to agents; the original document may contain an expected ruling. Use the prepared `ReviewInput`.

## Sample policy choices

These are implementation assumptions, not official Ryde policy:

1. Waiting starts at recorded driver arrival, including arrival before scheduled pickup. Here 08:43–08:51 is eight minutes. Starting at scheduled pickup instead would give six minutes.
2. Five minutes is the free-wait period; eight minutes is the no-show time threshold. The five-minute expiry alone is insufficient for the eight-minute condition.
3. The sample charge is SGD 5.00, designated as driver compensation.
4. GPS describes the recorded driver location; it cannot establish where the rider stood or which entrance was designated. There is no independent mandatory contact-count rule in this sample.
5. Ratings, dispute history, and fraud flags do not determine fee validity.
6. Material unresolved contradictions or missing evidence require human review.

Known conflict: `EVENT-008` says the charge becomes applicable after five minutes. That wording conflicts with the eight-minute sample rule. Preserve and expose the contradiction; do not rewrite the source record. `fee_eligible` in `checks.py` is only the time-threshold condition, not a final policy-compliant ruling.

## Actions and outcomes

- `request_rebuttal`: requires a nonblank `question` and `rebuttal_roles`; no ruling or proposed action. Target roles are `rider_advocate` and/or `driver_advocate`.
- `final_ruling`: requires `ruling` and `proposed_action`; no follow-up question.
- `human_review`: requires an explanation; no ruling or proposed action. Human review is an action/status, not a ruling enum.
- Rulings: `uphold_charge` (keep fee, zero refund), `reverse_charge` (recommend returning the full charged amount), `partial_refund` (return part of it), and `no_action` (no monetary change).
- `proposed_action.amount_cents` means refund to the rider, not the original charge. It must be a nonnegative integer; currency is `SGD`. Uphold/no-action require zero cents. Python verifies a reversal equals the charge and a partial refund is positive and below the charge.
- Confidence is optional and bounded from 0 to 1. It cannot override evidence or policy checks.
- `WorkflowResult.status` is `completed` or `human_review`; it includes an activity log, Judge result, and validation issues. Person B must ensure status matches the validated result.

## Remaining work

1. Configure a permitted model endpoint and evaluate actual responses, latency, token use, and provider compatibility. The backend accepts `FAIRRIDE_API_KEY` or `OPENAI_API_KEY`, `FAIRRIDE_MODEL`, and optional `FAIRRIDE_BASE_URL`.
2. Add rider-favorable, driver-favorable, and ambiguous no-show cases, keeping expected answers outside model input.
3. Add route-deviation records, sample policy, facts, checks, and case selection in the UI.
4. Evaluate citation support and case outcomes. ID existence and the current deterministic checks cannot prove every natural-language claim.

## Verification and interface changes

Run `.venv/bin/python -m unittest discover -s tests -v`. Sixteen tests pass, covering wait facts, contracts, example workflow, concurrent advocates, rebuttal limit, amount checks, and mocked client request shape. No live AI behavior is tested.

When changing a shared interface, update `contracts.py`, this handoff, the examples, and relevant tests together. Notify the other person before integrating incompatible changes.
