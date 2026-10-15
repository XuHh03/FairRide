# Person B handoff — policy v2.1, contract v2.0

Updated 15 October 2026. The user selected the supplied Ryde Dispute Resolution Policy v2.1 as the governing project reference. Read `POLICY_V2_1_SPEC.md` before changing behavior. Earlier synthetic policies are archived and are not loaded by the active workflow.

## Implemented

- Judge input includes `decision_rules.required_refund_basis` from the dispute category. All final rulings must use that basis even when retaining the charge with zero refund (`excess_distance_fare` for route disputes, `cancellation_fee` for no-show). This clarifies the existing validator; persistent wrong/null bases still fail after the bounded correction. DISP-011's justified, notified and agreed detour retains the fare; its calculated excess-distance component is not a refund recommendation.
- Every final Judge ruling now requires a numeric `confidence` in [0, 1], including low-value no-show cases with no minimum policy threshold. Rebuttal requests and policy referrals can omit it. Missing scores use the existing single schema-correction retry and persistent failures remain operational validation failures; no default score is supplied. The UI labels confidence as self-reported, not calibrated.
- Completed decision summaries and JSON reports include `party_messages.rider` and `party_messages.driver`, each containing `action` and `explanation`. Overview presents these as “For the rider” and “For the driver” tabs. Both use the canonical grounded explanation and the accepted amounts; refunds and goodwill remain separate recommendations. Referrals/failures have `party_messages=None` and no final-result tabs. These are presentation messages, not external notifications or executed payments.
- No-show calculation uses five physical pickup minutes no earlier than scheduled pickup, verified arrival, and both a message and call before cancellation. Invalid fees cannot survive through `no_action`. A driver no-show without contact has a separate goodwill-credit recommendation.
- Route calculations use additional kilometres and excess-distance fare. Historical traffic evidence, timely notification and acknowledgment are checked separately. Routes above 2 km, safety, high value and insufficient confidence are policy referrals.
- User decision: justified but unnotified routes are referred until the source's unspecified partial-refund formula is confirmed.
- The second Judge receives its original assessment/question and an exhausted rebuttal budget. Python still enforces one round.
- Live calls provide separate allowed evidence/policy ID lists. Citation, schema and overlong-statement errors share one response-correction retry per agent invocation (at most two calls total). It receives the invalid response and exact errors; overlong statements are rewritten concisely, never truncated. Persistent errors and invalid JSON still fail validation. This technical retry does not consume or extend the dispute rebuttal round. Activity logs report `citation_retries` and `schema_retries`; token totals include both calls.
- Before citation validation, known `FACT-*` references in evidence fields are expanded into the source IDs recorded on those facts in `ReviewInput`. All target sources must exist; unknown facts, empty provenance and invalid source mappings remain invalid. This mechanical resolution changes no statements, policy citations, rulings, amounts or confidence and makes no extra model call. Activity logs and the UI show `citation_resolutions`. Resolving a citation proves traceability, not that the claim accurately describes the evidence.
- Live Judge decisions get one policy-validation correction attempt on cases without material uncertainty or mandatory referral. It receives the original response, exact errors and policy-derived ruling/amount/basis requirements; these are calculated from case records, not evaluation labels. Missing precedents, wrong refunds and unsupported human-review decisions can be corrected. Numeric thresholds and the required precedent ID are explicit in the Judge payload. The correction cannot start another rebuttal. Confidence below the required threshold and real evidence conflicts remain referrals; confidence must not be raised just to pass validation. Persistent invalid decisions are operational validation failures and shown separately from evidence-based human review.
- Advocate outputs have no count cap on claims or optional counterpoints. Convey the main points and decisive evidence, combining supporting records into one claim's citations and avoiding duplicate arguments/calculations. One or two short sentences is prompt guidance; sentence count is not a validation rule. Each statement has a 1500-character runaway-response guard, not a target length. Prompts allow concessions and explicitly describe the inclusive arrival boundary, contacts before cancellation, full excess-distance refund and justified/agreed detour. Each live advocate receives `policy_application`, a concise summary derived from its supplied facts, not evaluation labels. These checks constrain format; they do not prove every statement is factually supported.
- Completed results add `WorkflowResult.final_explanation`, an application-generated rationale using validated case facts and the accepted refund. It is `None` for referrals and operational failures. `judge_result.explanation` and the logged original Judge responses remain unchanged for audit. The UI uses `final_explanation` for completed reviews, labels original live model analysis as unverified and distinguishes hand-written examples. Preserve these distinctions when redesigning the UI; citation existence is not factual validation.
- The live backend implements optional `review_argument(review, argument, question=None)` and `correct_advocate(review, role, feedback, question=None)` methods. The workflow checks each initial argument and rebuttal before the Judge. Reviews return `ArgumentReview.findings`, each with `section` (`claims`/`counterpoints`), zero-based `index`, `verdict` (`supported`/`unsupported`), concise explanation and citations. Python validates addresses and source IDs. Only unsupported verdicts trigger one semantic rewrite, followed by another support review; persistent findings or malformed reviews stop before the Judge as operational validation failures. Original/corrected arguments, findings, duration, usage and `support_status` are logged. Examples and custom backends without these methods keep their existing behavior and are not implicitly reviewed.
- Eleven cases, example outputs, evaluation labels and citations are migrated. Example responses are hand-written, not model results.
- The policy includes category-relevant precedent clauses. Profiles/history remain excluded from agent input; a derived confidence requirement reflects fraud flags. Verified rolling no-show records may flag the account for manual review, not establish fault.

## PR #6 integration — 15 October 2026

Integrated dashboard merge `88e00dc` with the three Person A commits ending at `bc86b74`. Both histories are preserved. The integration adds no model calls to the default demo flow.

| Overlap or issue | Resolution |
|---|---|
| `app.py` layout conflict | Keep PR #6's sidebar and four dashboard views; carry over the original/corrected argument labels and support-review findings into Agent activity. |
| Two independent final-reason generators | `checks.grounded_final_explanation` generates both the workflow explanation and dashboard/report reason. Original Judge prose remains separate in activity and the exported workflow. |
| Fact validation applied to support-review output | Advocate and Judge responses receive fact-assertion instructions/validation. `ArgumentReview` has a separate findings schema and validates finding citations without requiring nonexistent `fact_assertions`. |
| Competing response-repair paths | Length, schema, fact-value and citation errors share the same two-attempt generation loop. A known wrong fact cannot be hidden by removing its assertion during that repair. |
| Both branches added `tests/test_review_ui.py` | Preserve both test classes, adapt the earlier tests to sidebar navigation, and retain failure/status/source inspection checks. |
| Uncorroborated wait shown as a met physical-presence condition | Mark physical waiting unresolved when arrival is unverified; label its calculation as a recorded interval rather than proven physical waiting. |
| Appended facts and provenance | Keep the original fact IDs, PR #6's added timestamps/arrival facts and its narrower source mappings. |
| Experimental checker overhead and imperfect accuracy | Keep `FAIRRIDE_CHECK_ARGUMENT_SUPPORT=0` by default; opt-in behavior and findings remain available. |

Remaining issues:

- **Issue #5 stays open:** optional fact assertions validate only declared values. Models may omit assertions or write incorrect prose alongside correct values. The extra model checker previously missed a DISP-003 timestamp error and is not proof of accuracy.
- The integrated live comparison passed 10/11 checker-off and 4/4 targeted checker-on checks. DISP-011 timed out in the baseline Judge call; that operational failure remains recorded. Combined-schema provider reliability needs repeat evaluation. The checker repaired two arguments, but its own prose misstated a timely-presence fact; source inspection remains necessary. See `evaluations/integration-live-2026-10-15.json` and the integrated comparison in `EVALUATION.md`.
- The justified-but-unnotified partial-refund formula is still unspecified in the supplied policy. Keep that scenario in human review until the formula is confirmed.

Integration verification: 162 tests ran, 161 passed and one live batch was skipped. This includes all eleven demo cases across dashboard views, navigation without agent calls, exports, source citations, failure visibility and four new integration regressions. No paid model calls were made for this integration. The first two issue fixes (grounded explanations and overlength correction) are retained; the accuracy limitation is not marked resolved.

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

Support checking is off by default for the demo; set `FAIRRIDE_CHECK_ARGUMENT_SUPPORT=1` to opt in on the live backend. When enabled, it adds visible progress stages. Each advocate invocation has at most one semantic rewrite; initial arguments and rebuttals have separate invocation budgets. Each generation or support-review call separately retains the one shared schema/citation repair. A worst-case invocation makes at most eight requests (two generation, two support-review, two rewrite, two re-review); normally it makes two. This does not add a dispute rebuttal round. Evaluation counts support-review tokens in the advocate pipeline total. Failed calls can still lack usage metadata. Model support verdicts are not deterministic factual validation; a remaining DISP-003 timestamp error is documented in `evaluations/argument-review-2026-10-15.json`.

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
