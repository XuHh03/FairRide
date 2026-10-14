# Person B handoff — policy v2.1, contract v2.0

Updated 14 October 2026. The user selected the supplied Ryde Dispute Resolution Policy v2.1 as the governing project reference. Read `POLICY_V2_1_SPEC.md` before changing behavior. Earlier synthetic policies are archived and are not loaded by the active workflow.

## Implemented

- No-show calculation uses five physical pickup minutes no earlier than scheduled pickup, verified arrival, and both a message and call before cancellation. Invalid fees cannot survive through `no_action`. A driver no-show without contact has a separate goodwill-credit recommendation.
- Route calculations use additional kilometres and excess-distance fare. Historical traffic evidence, timely notification and acknowledgment are checked separately. Routes above 2 km, safety, high value and insufficient confidence are policy referrals.
- User decision: justified but unnotified routes are referred until the source's unspecified partial-refund formula is confirmed.
- The second Judge receives its original assessment/question and an exhausted rebuttal budget. Python still enforces one round.
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
| `run_review(case, policy, backend=None)` | Records + optional backend → `WorkflowResult` |
| `AgentBackend.advocate(review, role, question=None)` | Async call → `AgentCall[AdvocateResult]` |
| `AgentBackend.judge(review, rider_argument, driver_argument, rebuttals=None, previous_assessment=None)` | Async call → `AgentCall[JudgeResult]` |

The synchronous `rider_advocate`, `driver_advocate` and `judge` wrappers remain in `agents.py`; the workflow uses the async backend interface. Custom backends must accept `previous_assessment`. Model clients and Judge share the configured model; there is no separate Judge-model environment variable.

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

Next: review the migration, configure/rehearse the app, evaluate the live provider explicitly, confirm the partial-refund and confidence-calibration details with organizers, and add a real historical-traffic adapter if required. Commit/push only when requested. Update contracts, examples, docs and tests together for interface changes.
