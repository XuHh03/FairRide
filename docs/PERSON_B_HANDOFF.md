# Person B handoff — shared foundation v1.0

Updated 5 October 2026. This records implemented work, not future agent behavior.

## Implemented by Person A's shared-foundation task

- `contracts.py`: Pydantic v2 input/output schemas, unknown-field rejection, cited claims, Judge action constraints, integer refund cents, and contract version `1.0`.
- `evidence.py`: evidence lookup, policy lookup, agent-input preparation, and citation existence checks.
- `cases/DISP-002.json`: explicit, stable IDs on the ticket, trip, GPS, chats, and app events. Original record values are retained; profile history remains in the raw fixture but is excluded from agent input.
- `policies/sample_no_show.json`: version `1.0`, six individually identified sample clauses, and explicit policy assumptions.
- `checks.py`: waiting-time calculation now follows `wait_start_event`. The fixture still gives eight minutes with the arrival-based rule.
- `examples/agent_outputs.json`: hand-written examples of both advocates and all three Judge actions. These are interface examples, not model results or evaluation labels.
- `agents.py` and `workflow.py`: placeholder signatures now reference shared types.
- `tests/test_shared_contract.py`: executable shared-interface checks, alongside existing no-show tests.

## Not implemented

No model client, advocate model calls, Judge model calls, rebuttal execution, final policy/amount validation, route-deviation facts, or result UI exists yet. `agents.py` and `workflow.py` still raise `NotImplementedError`. The screen remains a read-only Streamlit fixture viewer.

## Public interfaces

| Function | Input | Output |
|---|---|---|
| `case_data.load_case(case_id)` | `"DISP-002"` | Raw case dictionary |
| `case_data.load_policy(policy_id)` | `"sample_no_show"` | Raw policy dictionary |
| `evidence.build_evidence_index(case)` | Raw case | ID → `EvidenceRecord` |
| `evidence.build_policy_index(policy)` | Raw policy | Clause ID → `PolicyClause` |
| `evidence.build_review_input(case, policy)` | Raw case and policy | `ReviewInput` |
| `evidence.validate_references(result, case, policy)` | Parsed advocate/Judge result and raw records | Error strings; empty list means all cited IDs exist |
| `agents.rider_advocate(review)` | `ReviewInput` | `AdvocateResult` — placeholder |
| `agents.driver_advocate(review)` | `ReviewInput` | `AdvocateResult` — placeholder |
| `agents.judge(review, rider_argument, driver_argument, rebuttals=None)` | Shared typed input and outputs | `JudgeResult` — placeholder |
| `workflow.run_review(case, policy)` | Raw case and policy | `WorkflowResult` — placeholder |

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
- `proposed_action.amount_cents` means refund to the rider, not the original charge. It must be a nonnegative integer; currency is `SGD`. Uphold/no-action require zero cents. Python must verify a reversal equals the charge and a partial refund is positive and below the charge. Those case-dependent amount checks remain to be built.
- Confidence is optional and bounded from 0 to 1. It cannot override evidence or policy checks.
- `WorkflowResult.status` is `completed` or `human_review`; it includes an activity log, Judge result, and validation issues. Person B must ensure status matches the validated result.

## Person A's remaining work

1. Add the shared model connection and API-key configuration, then implement both advocates against `ReviewInput` and `AdvocateResult`.
2. Prepare rider-favorable, driver-favorable, and ambiguous no-show cases, keeping expected outcomes outside agent inputs.
3. Add the advocate follow-up-question interface with Person B and build the evidence section of the UI.

## Person B's next work

1. Implement `judge` against the shared input and both advocate results. Use the fixtures while Person A builds the real advocates.
2. Implement `run_review`: prepare input, call advocates, parse/check outputs, call Judge, optionally route one specific rebuttal question, then Judge again.
3. Add a question input for advocate rebuttals together with Person A before coding that call. The current advocate signatures cover initial arguments only.
4. Reject invalid schemas and citations; enforce one rebuttal round and refer unresolved or invalid results for human review.
5. Build case-dependent policy and refund checks in Python. The Judge must not execute payments.
6. Connect validated results and the visible activity log to the UI. Add route-deviation fixtures and calculations separately.

## Verification and interface changes

Run `python3 -m unittest discover -s tests -v`. Nine tests cover existing wait facts, citation resolution/errors, missing/duplicate source IDs, profile exclusion, derived provenance, Judge action fields, output examples, and the configurable wait clock. No live AI behavior is tested.

When changing a shared interface, update `contracts.py`, this handoff, the examples, and relevant tests together. Notify the other person before integrating incompatible changes.
