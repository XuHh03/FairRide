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

The subsequent [issues #3–#5 review](evaluations/issues-3-5-review-2026-10-14.json) passed an eleven-case live batch and four targeted follow-up checks after explanation/retry fixes. Advocate prose still failed the follow-up audit in three cases; issue #5 remains open for accuracy work. The UI keeps this unverified analysis separate from the grounded final explanation.

The [15 October argument-review follow-up](evaluations/argument-review-2026-10-15.json) tested a model support check and one rewrite before arguments reach the Judge. Revised checks passed 3/4 cases and a later targeted follow-up passed 2/2; an escaped timestamp error shows why model support verdicts still require source inspection. This experimental check is **off by default** for the demo. Set `FAIRRIDE_CHECK_ARGUMENT_SUPPORT=1` before starting the app to opt in; it normally increases a clear review from three to five model calls.

The subsequent [integrated live comparison](evaluations/integration-live-2026-10-15.json) passed 10/11 checker-off and 4/4 targeted checker-on decision checks. One baseline Judge request timed out. The checker repaired two arguments, but reviewer prose still contained errors; issue #5 remains open. For three successful pairs it used 3.32× the wall time and 2.69× the reported tokens. These single-run observations do not establish reliability or production accuracy.

## Policy and implementation

- `policies/ryde_v2_1_*.json`: active, source-linked policy and category precedents. Earlier rules are archived.
- `checks.py`: waiting/contact/location calculations, route and excess-distance fare, safety/value/confidence safeguards, and final validation.
- `contracts.py`, `evidence.py`: contract v2.0, source lookup and prepared inputs; citation existence is not proof of claim support.
- `agents.py`, `workflow.py`: live/example backends, concurrent advocates, one rebuttal round, and original-question context on the second Judge call. Schema, citation, length and fact-value errors share one repair per generation call; support reviews use their own schema/citation repair. Live advocates receive computed policy context; experimental support checks remain off by default. Clear invalid Judge decisions get one policy-validation correction. Persistent errors are displayed separately from evidence-based human review.
- `review_summary.py`: dashboard checklist, timeline, calculations and review-report export. The dashboard uses the same grounded final-explanation generator as the workflow. Optional `fact_assertions` on advocate claims and Judge outputs bind declared values to supplied Python facts; existing outputs without assertions remain compatible. This checks declared values, not every statement in model prose.
- `cases/`, `examples/`, `evaluation.py`: raw records, separate hand-written responses and separate expected labels.
- `app.py`: live progress, case review, activity, cited evidence, refund and separate goodwill-credit recommendations. Completed reviews display an application-generated explanation from validated facts; original Judge and advocate prose remains inspectable and labelled as model analysis. Known `FACT-*` citations are resolved to their recorded sources and shown in the activity log without extra model calls; unknown IDs remain invalid.

Traffic evidence is supplied input or explicitly synthetic historical-API fixtures; no live traffic adapter exists. Partial excess-distance refunds for justified but unnotified detours are referred until the undefined formula is confirmed. Confidence gates are enforced, but empirical calibration is still unverified. Unsupported categories are referred.

Read [the guide](docs/PROJECT_GUIDE.md), [v2.1 spec](docs/POLICY_V2_1_SPEC.md), [handoff](docs/PERSON_B_HANDOFF.md), and [evaluation definitions](docs/EVALUATION.md). Historical saved results and older increment 1 proposals do not describe the current policy.

PR #6 integration resolutions and remaining issues are recorded in the [team handoff](docs/PERSON_B_HANDOFF.md#pr-6-integration--15-october-2026).
