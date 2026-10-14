# Person B handoff — policy v2.1, contract v2.0

Updated 14 October 2026. The user selected the supplied Ryde Dispute Resolution Policy v2.1 as the governing project reference. Read `POLICY_V2_1_SPEC.md` before changing behavior. Earlier synthetic policies are archived and are not loaded by the active workflow.

## Implemented

- No-show calculation uses five physical pickup minutes no earlier than scheduled pickup, verified arrival, and both a message and call before cancellation. Invalid fees cannot survive through `no_action`. A driver no-show without contact has a separate goodwill-credit recommendation.
- Route calculations use additional kilometres and excess-distance fare. Historical traffic evidence, timely notification and acknowledgment are checked separately. Routes above 2 km, safety, high value and insufficient confidence are policy referrals.
- User decision: justified but unnotified routes are referred until the source's unspecified partial-refund formula is confirmed.
- The second Judge receives its original assessment/question and an exhausted rebuttal budget. Python still enforces one round.
- Live calls provide separate allowed evidence/policy ID lists. Citation errors and repairable schema errors (such as a missing Judge explanation) share one response-correction retry per model call. It receives the invalid response and exact errors; the corrected response is validated again. Persistent errors and invalid JSON still fail validation. The runaway-length guard is not retried or truncated. This technical retry does not consume or extend the dispute rebuttal round. Activity logs report `citation_retries` and `schema_retries`; token totals include both calls.
- Before citation validation, known `FACT-*` references in evidence fields are expanded into the source IDs recorded on those facts in `ReviewInput`. All target sources must exist; unknown facts, empty provenance and invalid source mappings remain invalid. This mechanical resolution changes no statements, policy citations, rulings, amounts or confidence and makes no extra model call. Activity logs and the UI show `citation_resolutions`. Resolving a citation proves traceability, not that the claim accurately describes the evidence.
- Live Judge decisions get one policy-validation correction attempt on cases without material uncertainty or mandatory referral. It receives the original response, exact errors and policy-derived ruling/amount/basis requirements; these are calculated from case records, not evaluation labels. Missing precedents, wrong refunds and unsupported human-review decisions can be corrected. Numeric thresholds and the required precedent ID are explicit in the Judge payload. The correction cannot start another rebuttal. Confidence below the required threshold and real evidence conflicts remain referrals; confidence must not be raised just to pass validation. Persistent invalid decisions are operational validation failures and shown separately from evidence-based human review.
- Advocate outputs have no count cap on claims or optional counterpoints. Convey the main points and decisive evidence, combining supporting records into one claim's citations and avoiding duplicate arguments/calculations. One or two short sentences is prompt guidance; sentence count is not a validation rule. Each statement has a 1500-character runaway-response guard, not a target length. Prompts allow concessions when the evidence supports the other side and prohibit invented obligations, repetition and deliberation. Live advocates receive the output schema. Overlong statements are rejected as validation failures, not truncated or retried by the citation-correction path. These checks constrain format; they do not prove every statement is factually supported.
- Eleven cases, example outputs, evaluation labels and citations are migrated. Example responses are hand-written, not model results.
- The policy includes category-relevant precedent clauses. Profiles/history remain excluded from agent input; a derived confidence requirement reflects fraud flags. Verified rolling no-show records may flag the account for manual review, not establish fault.

## Public interfaces

| Function | Input → output |
|---|---|
| `load_case(case_id)` | Case ID → raw case dictionary |
| `policy_for_case(case)` | Raw case → active v2.1 policy dictionary |
| `build_evidence_index(case)` | Raw case → ID-to-`EvidenceRecord` lookup |
| `build_policy_index(policy)` | Policy → clause lookup, including relevant precedent |
| `build_review_input(case, policy)` | Raw records → contract-v2 `ReviewInput` |
| `validate_references(result, case, policy)` | Parsed result → unknown-ID issues |
| `run_review(case, policy, backend=None, *, on_progress=None)` | Records + optional backend/progress callback → `WorkflowResult` |
| `AgentBackend.advocate(review, role, question=None)` | Async call → `AgentCall[AdvocateResult]` |
| `AgentBackend.judge(review, rider_argument, driver_argument, rebuttals=None, previous_assessment=None)` | Async call → `AgentCall[JudgeResult]` |

The synchronous `rider_advocate`, `driver_advocate` and `judge` wrappers remain in `agents.py`; the workflow uses the async backend interface. Custom backends must accept `previous_assessment`. Model clients and Judge share the configured model; there is no separate Judge-model environment variable.

An optional async `correct_judgment(review, rider_argument, driver_argument, validation_feedback, rebuttals=None, previous_assessment=None)` method enables the bounded decision-correction path. The live backend implements it; example/custom backends without it retain validation rejection. It returns `AgentCall[JudgeResult]`. Correction calls and their usage are recorded separately as `decision_correction`; the shared schema/citation retry remains bounded within each model call.

`on_progress(message)` is optional on both `run_review` and `run_review_async`. It runs on the calling thread before each workflow stage and after advocates finish. Streamlit uses it to update an expanded status panel during evidence preparation, advocate analysis, initial Judge review, optional rebuttal/final Judge review, and final validation. The final panel distinguishes completion, required human review, and operational failure. Advocates analyze supplied records; they do not collect new external evidence.

## Runnable example — no API key

Run from the repository root after installing `requirements.txt`:

```python
from agents import ExampleAgentBackend
from case_data import load_case, policy_for_case
from evidence import build_review_input
from workflow import run_review

case = load_case("DISP-012")
policy = policy_for_case(case)
review = build_review_input(case, policy)
result = run_review(case, policy, ExampleAgentBackend())
print(review.contract_version, policy["version"], result.status)
assert result.failure_category is None
assert sum(entry.actor == "judge" for entry in result.activity_log) == 2
```

For direct fixture access, use `examples[case_id][role]`: examples are grouped by case. They are never model inputs.

## Contracts and source IDs

- `Policy` carries version 2.1, `supplied_project_reference` status, source path, effective date, category, clauses and relevant thresholds. `SamplePolicy` is only an import alias for integration compatibility.
- `ReviewInput.contract_version` is 2.0. It contains source evidence, named derived facts, policy and `required_confidence`. Facts may be numeric, boolean or a state string. Cite underlying records, not `FACT-*` IDs.
- Original IDs remain stable. Historical traffic evidence uses `TRAFFIC-*`; policy section IDs are `POLICY-1.3`, `POLICY-2.3`, etc. Category precedents are `POLICY-7.1` or `POLICY-7.3`.
- Every final ruling cites a relevant precedent and explains similarity or distinction. A precedent amount is not a general refund formula.
- `proposed_action.amount_cents` is the rider refund; `goodwill_credit_cents` is separate. `refund_basis` is `cancellation_fee` or `excess_distance_fare`. All amounts are integer SGD cents. No actual payment occurs.
- `WorkflowResult.failure_category` distinguishes setup/model/validation failures. `mandatory_escalation` identifies required policy referrals, which are not failures. `account_review_flags` recommends human account review without executing restrictions.
- Log entries contain serialized results under `entry.output["result"]`, plus timing and permitted usage fields. Mandatory policy referrals may have only system entries because no Judge call is permitted.

## Decisions and limits

Five minutes is inclusive. Early arrival does not count; a late driver must spend five physical minutes after arrival. This late-arrival interpretation is documented, not stated explicitly in the source. Notification and acknowledgment are required by the deviation point in this implementation.

Use an explicit disputed amount where supplied; otherwise the charge is the conservative value bound. Confidence is self-reported and gated by policy; empirical calibration and a credibility weighting formula remain unavailable. Do not invent them.

Historical traffic records are supplied input or clearly marked synthetic API-response fixtures. No live traffic adapter is implemented. Missing traffic data must not become affirmative proof of no congestion. Fare/surge, property damage, and other categories remain unsupported and are referred; the supplied documents are retained for future work.

## Verify and continue

Run `FAIRRIDE_RUN_LIVE_TESTS=0 python3 -m unittest discover -s tests -v` and `python3 evaluation.py --output /tmp/fairride-v21.json`.

Next: inspect arguments and rejected Judge responses, repeat live regression runs for consistency, confirm the partial-refund and confidence-calibration details with organizers, and add a real historical-traffic adapter if required. Update contracts, examples, docs and tests together for interface changes.
