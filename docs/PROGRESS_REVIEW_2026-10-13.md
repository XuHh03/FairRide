# FairRide progress review — 13 October 2026

Review scope: fetched GitHub refs, compared all current branches, ran isolated offline test suites, inspected existing evaluation results, and reproduced validation failures without live API requests. This document records findings; it does not implement fixes.

## Branch status

| Ref | Commit | Implemented state | Offline verification |
|---|---|---|---|
| GitHub `origin/main` | `a27d3e0` | Original shared scaffold; agent/workflow placeholders remain. Includes agent guide and progress snapshot. | 9 passed |
| Local `main` | `cf6271b` | Alternate agents package/client implementation, no-show loop and three no-show cases. Diverged from GitHub main: three ahead, two behind. | 38 passed, 3 live tests skipped |
| `origin/feat/no-show-review-workflow` | `f647d09` | Chat client and agent backend, parallel advocates, Judge, bounded rebuttal, final validation, example/live UI for the original no-show case. | 16 passed |
| `person-a/no-show-advocates` / its remote | `903dac3` | Merges the workflow branch, adds six cases across no-show and route deviation, case selection, prompt changes, batch evaluation, and saved example/live results. Uses the backend architecture in `agents.py`. | 46 passed, 6 live tests skipped |

The Person A branch already contains the workflow branch and local main's earlier commits. Review its final tree as the integration candidate; do not attempt to combine the two alternative agent architectures again. Tests were run on temporary branch snapshots without changing the checkout.

## What is working

- Stable source IDs, Pydantic response contracts, source lookups, and profile exclusion from model input.
- Configurable chat-completions endpoint and distinct advocate/Judge roles.
- Concurrent initial advocate calls, one optional rebuttal round, and conservative failure fallback.
- Python wait and route calculations, proposed-refund checks, and cited activity records.
- Six selectable example cases and hand-written example outputs.
- Saved live evaluation results exist for all six cases; their reported model quality was not independently rerun in this review.

## Priority 1: make evaluation failures visible

`evaluation.py:278` accepts human review as a matching outcome for every label. `evaluation.py:292` also counts human review as amount-correct, including setup and transport failures. `tests/test_evaluation.py` follows the same acceptance behavior.

Reproduction: remove API/model configuration and call `run_single_case(case_id, "live")` for all six labels. Every run reports a setup failure and human review, yet the summary reports a ruling match rate of 1.0. This permits a completely nonfunctional provider path to score 100%.

Changes needed:

- Separate operational failures, intentional abstentions, and actual rulings.
- Use explicit human-review expectations for truly ambiguous cases; do not accept universal abstention as ruling accuracy.
- Report exact ruling accuracy, successful completion/coverage, abstention rate, and provider/schema/citation failures separately.
- Require explicit opt-in for paid live tests, beyond merely detecting credentials in `.env`.
- Save timestamp, model/provider, prompt version or hash, case/policy versions, and Git commit with evaluation results.

## Priority 1: implement route justification consistently

`checks.py:179` rejects any upheld significant deviation. It does not apply the documented policy exceptions for traffic alerts, road closures, or rider-requested changes. Conversely, a partial refund can pass even when justification is corroborated.

Reproduction: add a documented traffic-incident alert to `DISP-005`. An upheld charge is rejected solely because deviation exceeds 15%; a 750-cent refund passes despite that corroboration.

`checks.py:114`–`checks.py:120` uses substring matching: an event saying that no traffic alerts were active counts as corroboration because it contains both words. Negative evidence and positive confirmation must be distinguished.

Changes needed:

- Represent route exceptions explicitly and distinguish corroborated, unsupported, contradicted, and unresolved justifications.
- Apply those facts in both the prompt and Python final validation.
- Distinguish evidence insufficiency from an unjustified deviation that the sample policy can resolve.
- Add a driver-favorable justified-detour case and an ambiguous route case. The two current route cases cover an unjustified large deviation and a below-threshold deviation.

## Priority 1: close the no-action validation gap

`checks.py:156` checks time eligibility for `uphold_charge`, but not `no_action`. On `DISP-007`, a five-minute wait below the eight-minute threshold can produce `no_action` with zero refund and no validation issues. That leaves an invalid charge unchanged.

Clarify when `no_action` is allowed and enforce the same fee-validity conditions whenever the charged fee is retained. Add a regression test.

## Priority 2: reconcile fare evidence and validate route input

`DISP-005`'s listed fare components sum to SGD 26.61, while its stated charged total is SGD 31.00. The validator does not flag that mismatch even though sample POLICY-005 requires fare consistency. The 750-cent refund uses the trip-level total instead.

Changes needed:

- Reconcile itemized fares, stated totals, and trip fields, or explicitly record any missing fee component.
- Reject zero/negative planned distance and invalid monetary precision rather than deriving misleading route percentages or truncating cents.
- Add regression cases for contradictory totals and malformed route records.
- In `evidence.py:93`, resolve the relevant trip/fare IDs from actual records rather than hardcoding `TRIP-001`, `FARE-005`, and `FARE-006`. Validate derived-fact provenance too.

## Priority 2: preserve rebuttal context

`workflow.py:96` sends the initial arguments and rebuttal answers to the second Judge call, but `ModelAgentBackend.judge` omits the Judge's previous question and provisional assessment from the payload. The next call is stateless; it must infer what was asked.

Pass the previous question/assessment explicitly, and tell the second pass that the rebuttal budget is exhausted. Update the shared interface and tests together. Keep one-round enforcement in Python.

## Priority 2: refresh documentation and demo setup

- `progress.md` still says one case, 16 tests, no route support, and no live provider calls. That no longer describes the Person A branch.
- The product/technical specs are proposals based on an older scaffold; mark delivered sections and reconcile their package/client design with the current backend implementation.
- `app.py` labels DISP-007 as an SGD 8 fee, while the fixture and evaluation use SGD 5.
- The documented local `.venv` is absent, and the available system Python lacks Streamlit. The app was inspected but UI execution could not be verified in this review. Recreate the declared environment and smoke-test all six example cases.
- Keep sample policies clearly labelled. Confirm dataset-specific rules with organizers before claiming official Ryde-policy compliance.

## Recommended ownership and sequence

1. Person A: repair evaluation accounting, case/fare evidence, and provenance; add missing route examples.
2. Person B: repair route/no-action final validation and explicit rebuttal context.
3. Together: align Judge instructions, policy clauses, and deterministic checks; rerun offline regression tests.
4. Recreate the app environment; test all example cases in the UI, then explicitly run and inspect live evaluations.
5. Refresh progress/spec/handoff documents and open a reviewed PR from the Person A branch to GitHub main.
6. Finish the walkthrough, architecture diagram, submission assets, and required development-conversation evidence. Avoid introducing new orchestration or retrieval frameworks at this stage.
