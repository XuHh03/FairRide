# FairRide

FairRide reviews no-show charges and route deviations using Rider Advocate, Driver Advocate and Judge roles, cited evidence, and deterministic policy checks. It follows the supplied **RydeResolve Policy v2.1** project reference. Eleven demo cases are synthetic; recommendations never execute payments or account actions.

## Run

Use Python 3.12 or newer:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

Example walkthroughs require no API key. For live calls, set required `FAIRRIDE_API_KEY` (or `OPENAI_API_KEY`) and `FAIRRIDE_MODEL`. Optional `FAIRRIDE_BASE_URL` selects an OpenAI-compatible endpoint. `.env.example` lists supported settings; keep real credentials out of Git. No separate Judge-model or stub environment switch is implemented.

The app shows evidence preparation, advocate analysis, Judge review, optional rebuttal, decision correction and final validation as they run. Use one app server; restart it after backend changes if imported code remains stale.

To start from a complaint, enable **File a dispute** in the sidebar, select a demo trip, enter what happened, choose a review mode and click **File dispute and run review**. Live mode lets each advocate request local sources before arguing. The planner initially sees the complaint, trip reference, policy and available source names; requested records are returned through read-only tools. Both advocates have equal access and must retrieve every available source before arguing, with at most three selection calls each. Requests, returned record IDs, duration and available token usage appear in **Agent activity** and JSON exports. Example mode makes scripted requests and uses hand-written arguments; it does not demonstrate live model autonomy. Filing edits exist only in memory, and each demo trip retains its supplied dispute category.

To try a new dataset case, use **Import case JSON** in the sidebar and select one raw no-show or route-deviation JSON file (up to 2 MiB). Use an input file from the dataset's `cases` folder, keeping answer keys and evaluation reports separate. The app preserves its IDs and prefills an editable complaint. Imported cases use **Live model** only; click **File dispute and run review** to start evidence retrieval and review. Uploading alone makes no model calls. Files and complaint edits remain in the current session; remove the file to return to demo cases. Changing or removing the uploaded evidence clears the previous review and export. Invalid files display an import error. Follow the existing raw case templates; this validation checks compatibility with the app, rather than providing a formal raw JSON schema.

Filed live disputes normally add two model calls for source selection (one per advocate), up to six total retrieval calls if they request sources in stages. Existing case selection and evaluation callers retain their prepared-package path. Policy-mandated preflight referrals still skip agent calls. Retrieval schema, trip or budget failures issue no ruling. The [15 October filing live check](evaluations/filing-live-2026-10-15.json) ran DISP-004 and DISP-010 twice each on `f140733`: all four passed decision/retrieval/dashboard checks, with 3–5 retrieval calls per review. Manual prose inspection still found a wrong fee recipient and incorrect tolerance-deduction arithmetic in original model commentary; the grounded final explanations remained correct. This small check does not clear issue #5 or establish production reliability.

On the third and final retrieval call, the model receives a schema requiring exactly the remaining source names without duplicates; the tool boundary enforces the same condition. Incomplete requests still fail operationally, without silently fetching extra sources or adding calls. For no-show cases, conflicting reported arrival and relevant pickup-window GPS require human review when the elapsed no-contact case leaves the separate goodwill entitlement unresolved. The fee refund may be clear while goodwill remains uncertain. A new derived fact, `goodwill_eligibility_resolved`, makes that distinction explicit; computed credit alone does not settle the conflict.

The dashboard sidebar contains case selection, review mode, the run button, navigation and report download. Overview focuses on the decision, key metrics, a compact policy checklist and explicit wait/distance/fare calculations. Select Evidence for detailed checks and the chronological timeline, Agent activity for collapsed commentary, or Sources & policy to browse records. Citation buttons open source records in place. Free-text explanations are not semantically certified. Download the JSON review report to retain the summary, calculated facts, cited evidence, policy and workflow activity without raw profiles.

Route overviews also plot additional distance against the supplied policy's no-refund tolerance and AI distance limit. These distance boundaries alone do not determine fault or the refund. No-show overviews retain the concise wait metrics and timeline.

## Testing

Run offline checks and the hand-written example batch:

```bash
FAIRRIDE_RUN_LIVE_TESTS=0 .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python evaluation.py --output /tmp/fairride-v21.json
```

Run the live regression suite with configured credentials and model:

```bash
FAIRRIDE_RUN_LIVE_TESTS=1 .venv/bin/python -m unittest discover -s tests -p test_evaluation.py -v
```

This makes paid model calls and prints each case, current stage, PASS/FAIL, ruling, refund, duration and tokens. Clear cases must match exact expected rulings and fixed refund/credit/basis labels; model failures and unexpected referrals fail the test. Without credentials/model or explicit opt-in, the live batch is skipped. Expected labels remain outside agent input.

For repeated measurements and a saved report:

```bash
.venv/bin/python evaluation.py --live --runs 3 --output /tmp/fairride-live-regression.json
```

The CLI produces a report; use the unit test for a pass/fail gate. The latest three-run review passed 32 of 33 case checks, with one rejected overlong advocate response. All accepted final amounts matched their expected values, but some generated prose contained factual errors; see [the review report](evaluations/pr2-review-2026-10-14.json) and [progress](progress.md). These synthetic cases do not establish production accuracy.

For an external held-out dataset, use `heldout_evaluation.py`. Each raw input must be named after its dispute ID, with an identically named JSON key in a separate folder. For the current local dataset, check inputs and key filenames without provider calls first:

```bash
.venv/bin/python heldout_evaluation.py \
  --cases-dir ../FairRide-held-out-v21-20261016/cases \
  --answer-key-dir ../FairRide-held-out-v21-20261016/answer_key \
  --dry-run
```

Then opt in to the live batch using your configured endpoint and model:

```bash
.venv/bin/python heldout_evaluation.py \
  --cases-dir ../FairRide-held-out-v21-20261016/cases \
  --answer-key-dir ../FairRide-held-out-v21-20261016/answer_key \
  --live --runs 1 --output /tmp/fairride-heldout.json
```

This runs the imported-case path with advocate evidence retrieval, prints case/stage progress and PASS/FAIL, and checkpoints the JSON report after every case. Use `--runs 3` for repeated observations. Exit status is 0 when all checks pass, 1 for a completed batch with failures, or 2 for command/input setup errors. Inputs and matching key filenames are checked before any calls; key contents are read only after each review returns. Dry run does not check answer-key contents. The report must be outside both source folders, and its destination is checked before spending model calls.

The evaluator compares fixed external refund, goodwill and basis labels, outcomes, final confidence, citation existence and complete per-role evidence retrieval before arguments within the three-call budget. Policy preflight referrals skip retrieval. Conditional labels permit a referral only when a recorded confidence is below the stated threshold; operational failures never count as appropriate referrals. Keys use `case_id`, `expected_label`, `expected_refund_cents`, `expected_goodwill_credit_cents`, `refund_basis`, `mandatory_human_review` and `confidence_requirement.policy_threshold`; inspect the evaluator's tests for supported label names. The report retains key status and confirmation flags: the supplied keys are drafts, so matches are provisional. Review saved advocate/Judge commentary against source evidence manually; citation existence and decision checks do not certify its meaning or confidence calibration. No extra LLM reviewer is used.

Held-out report version `heldout-1.1` separates `checks.retrieval` (source coverage, timing and call budget) from `checks.argument_completion` (both validated initial arguments are present). A response-validation failure after successful reads no longer reports missing evidence. Both checks are skipped for policy preflight referrals; operational failures remain failures regardless of source coverage.

The latest [16 October live regression batch](evaluations/heldout-live-followup-2026-10-16.json) matched all 12 draft keys with zero operational failures: seven final rulings and five referrals, including one confidence referral (90% against a 95% requirement). The [targeted cases 2 and 6 rerun](evaluations/claim-feedback-live-followup-2026-10-16.json) also passed both checks: a 500-cent refund with no goodwill, and a supported goodwill-conflict referral, respectively. Both used `qwen3.6:35b`. The user reported completing the explanation review and supplied no material findings. That review is user-reported, not independent semantic certification. The reports are preserved unchanged from the local runs; earlier diagnostic failures remain available. These inspected cases are now regression cases. Draft answer keys, small run counts and the remaining free-prose limitations preclude generalisation or production-reliability claims; use a fresh untouched set for that assessment.

The subsequent [issues #3–#5 review](evaluations/issues-3-5-review-2026-10-14.json) passed an eleven-case live batch and four targeted follow-up checks after explanation/retry fixes. Advocate prose still failed the follow-up audit in three cases; issue #5 remains open for accuracy work. The UI keeps this unverified analysis separate from the grounded final explanation.

The [15 October argument-review follow-up](evaluations/argument-review-2026-10-15.json) tested a model support check and one rewrite before arguments reach the Judge. Revised checks passed 3/4 cases and a later targeted follow-up passed 2/2; an escaped timestamp error shows why model support verdicts still require source inspection. This experimental check is **off by default** for the demo. Set `FAIRRIDE_CHECK_ARGUMENT_SUPPORT=1` before starting the app to opt in; it normally increases a clear review from three to five model calls.

The subsequent [integrated live comparison](evaluations/integration-live-2026-10-15.json) passed 10/11 checker-off and 4/4 targeted checker-on decision checks. One baseline Judge request timed out. The checker repaired two arguments, but reviewer prose still contained errors; issue #5 remains open. For three successful pairs it used 3.32× the wall time and 2.69× the reported tokens. These single-run observations do not establish reliability or production accuracy.

## Policy and implementation

- Two recorded prose contradictions have narrow checks that reuse the existing correction budget: assigning valid no-show compensation to the rider and stating a reduced refundable/excess distance after subtracting tolerance. Both advocates and Judge receive the same Python-derived policy context. The [16 October follow-up](evaluations/filing-prose-final-2026-10-16.json) passed four decision/retrieval/dashboard checks with those targeted errors absent from accepted output. Other model prose errors remain, including wait-start and notification reasoning; these checks do not resolve issue #5 or certify arbitrary prose. The [first attempted follow-up](evaluations/filing-prose-followup-2026-10-16.json) is retained with its failed prose audit.
- `policies/ryde_v2_1_*.json`: active, source-linked policy and category precedents. Earlier rules are archived.
- `checks.py`: waiting/contact/location calculations, route and excess-distance fare, safety/value/confidence safeguards, and final validation.
- `contracts.py`, `evidence.py`: contract v2.0, source lookup and prepared inputs; citation existence is not proof of claim support.
- `case_data.py`, `retrieval.py`: in-memory complaint intake against the demo trip catalog and bounded, trip-scoped local evidence reads. Raw profiles, expected outcomes and arbitrary file/network queries are not exposed to retrieval planners.
- `agents.py`, `workflow.py`: live/example backends, concurrent advocates, one rebuttal round, and original-question context on the second Judge call. Schema, citation, length and fact-value errors share one repair per generation call; support reviews use their own schema/citation repair. Live advocates receive computed policy context; experimental support checks remain off by default. Clear invalid Judge decisions get one policy-validation correction. Persistent errors are displayed separately from evidence-based human review.

Fact-value repair requests explicitly include `required_fact_assertions` with canonical IDs and values for previously asserted known facts. Advocates must retain them on relevant claims/counterpoints; Judges retain them at the top level. Computed amounts remain distinct from unresolved entitlements. Dropping an assertion or persisting with a wrong value still fails within the same single repair budget.

Detected advocate fact/prose errors now add `schema_correction.claim_feedback`: the zero-based claim/counterpoint location, original statement, detected offending sentences, errors, canonical facts and required correction. Feedback is sent only on a detected error and uses the existing repair attempt. A targeted prose check rejects explicit claims of verified pickup presence when the supplied arrival verification is false, including correctly copied false assertions accompanied by contradictory text. Reported, negated, hypothetical, off-site and explicitly post-cancellation statements are distinguished in regression tests. These bounded wording checks do not certify arbitrary prose. Per-attempt diagnostics retain the claim feedback for inspection.

To investigate schema/fact/prose/citation correction failures, inspect the evaluation report at `cases[].review.workflow.activity_log[].output.validation_diagnostics`. It records case ID, actor, response type, each returned JSON response, validation errors and required fact assertions sent for that attempt. Failed calls appear as `response_validation_failed`; successful repairs retain the same diagnostics on the accepted argument/Judge event. A transport or JSON-decoding failure records that no parsed response is available. Request payloads, headers and configuration are not captured; explicit profile, header and API-key fields are removed recursively from returned JSON snapshots. These are diagnostic responses, not validated evidence or decisions. Retry limits and failure classification are unchanged, and reported failed-call usage is included once.
- `review_summary.py`: dashboard checklist, timeline, calculations and review-report export. The dashboard uses the same grounded final-explanation generator as the workflow. Optional `fact_assertions` on advocate claims and Judge outputs bind declared values to supplied Python facts; existing outputs without assertions remain compatible. This checks declared values, not every statement in model prose.
- `cases/`, `examples/`, `evaluation.py`: raw records, separate hand-written responses and separate expected labels.
- `app.py`: live progress, case review, activity, cited evidence, refund and separate goodwill-credit recommendations. Completed reviews display an application-generated explanation from validated facts; original Judge and advocate prose remains inspectable and labelled as model analysis. Known `FACT-*` citations are resolved to their recorded sources and shown in the activity log without extra model calls; unknown IDs remain invalid.

Traffic evidence is supplied input or explicitly synthetic historical-API fixtures; no live traffic adapter exists. Partial excess-distance refunds for justified but unnotified detours are referred until the undefined formula is confirmed. Confidence gates are enforced, but empirical calibration is still unverified. Unsupported categories are referred.

Read [the guide](docs/PROJECT_GUIDE.md), [v2.1 spec](docs/POLICY_V2_1_SPEC.md), [handoff](docs/PERSON_B_HANDOFF.md), and [evaluation definitions](docs/EVALUATION.md). Historical saved results and older increment 1 proposals do not describe the current policy.

PR #6 integration resolutions and remaining issues are recorded in the [team handoff](docs/PERSON_B_HANDOFF.md#pr-6-integration--15-october-2026).
