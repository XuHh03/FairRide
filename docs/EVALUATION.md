# Evaluation scoring v2

Updated 14 October 2026. Policy reference: supplied v2.1. Evaluation measures correct autonomous resolution separately from referrals and failures. It does not change the application's human-review fallback.

## Labels and categories

`evaluation.LABELS` holds expected outcomes outside model inputs. DISP-005, DISP-008 and DISP-009 require human review because extra distance exceeds 2 km. DISP-012 expects human review for conflicting historical traffic records after one bounded rebuttal. The other seven cases expect a validated decision and amount; blanket human review is not accepted for clear cases. DISP-002 now meets the selected five-minute scheduled-pickup rule and contact obligations.

Refund amounts, separate goodwill credits and refund bases are fixed expected labels. Scoring does not reuse the application's `policy_outcome` calculation as its answer oracle. The report includes these expectations and the configured model name; expected labels are never sent to agents.

Each run has one category:

- `correct_ruling`: a validated final ruling and amount match the expected outcome.
- `incorrect_ruling`: a validated final ruling has the wrong outcome or amount.
- `appropriate_escalation`: an evidence-based referral on a case labelled human review, or a mandatory policy referral (including a confidence gate).
- `unnecessary_escalation`: an evidence-based referral on a case with a clear expected ruling.
- `operational_failure`: setup, model/transport, schema, citation, invalid-ruling, or rebuttal-limit failure prevented validated processing.

`WorkflowResult.failure_category` is an additive optional field: `setup`, `model`, `validation`, or null. Null means no technical/validation failure was recorded. A known material-evidence issue can legitimately cause human review without this field being set. Wrong amounts, unknown citations, malformed responses, and repeated rebuttal requests are validation failures. Scoring reads this field rather than parsing the explanation text.

Operational failures take precedence over the expected label. Even a failure on the ambiguous case must not count as an appropriate referral.

Unsupported Judge referrals on cases with complete evidence and no policy gate fail validation. The live backend gets one bounded decision correction first. Explicit confidence below the policy requirement or material uncertainty remains a referral; generic complexity, an allowed boundary, or an invented threshold is insufficient. Persistent incorrect decisions are operational failures rather than successful human-review outcomes.

## Metrics and denominators

| Metric | Formula |
|---|---|
| Autonomous resolution rate | Validated final rulings / all runs |
| Ruling accuracy | Correct final rulings and amounts / validated final rulings |
| Unnecessary escalation rate | Nonfailed human referrals on clear cases / all clear-case runs |
| Operational failure rate | Failed runs / all runs |
| Abstention rate | Nonfailed human referrals / all runs |

Accuracy is `null` in JSON and `N/A` in the console if no final rulings exist. Unnecessary escalation rate is also unavailable if there are no clear-case runs. A referral has no amount to verify: `amount_correct` is null rather than true. Failures do not also count as abstentions or successful amount checks.

`ruling_match` is true only for a correct final ruling; appropriate escalation uses its separate category. Summary v2 replaces the old `ruling_match_rate` with explicit `ruling_accuracy` and `autonomous_resolution_rate`. Report JSON carries `evaluation_version: "2.0"`.

## Run

```bash
python3 evaluation.py --output /tmp/fairride-example-v2.json
python3 -m unittest discover -s tests -v
```

The first command runs hand-written examples only. It currently gives seven correct final rulings and four appropriate referrals: 63.6% autonomous resolution and 100% accuracy among the seven final rulings. These are integration results, not evidence of live model accuracy.

Live evaluation requires explicit `--live` and configured credentials/model:

```bash
python3 evaluation.py --live --runs 3 --output /tmp/fairride-live-v2.json
```

Live unit tests additionally require `FAIRRIDE_RUN_LIVE_TESTS=1`. Credentials in `.env` alone do not enable them:

```bash
FAIRRIDE_RUN_LIVE_TESTS=1 python3 -m unittest discover -s tests -v
```

To run only the evaluation regression suite from the repository root:

```bash
FAIRRIDE_RUN_LIVE_TESTS=1 .venv/bin/python -m unittest discover -s tests -p test_evaluation.py -v
```

This makes paid model calls when credentials and `FAIRRIDE_MODEL` are available. Without them the live batch is skipped; inspect the test output before claiming a live pass. Seven clear cases must return their exact expected decision and fixed refund/credit/basis. Mandatory confidence referrals remain safe in production but fail the clear-case regression expectation. Required policy referrals and the ambiguous traffic case must return human review. Setup/model/schema/citation/decision failures fail the batch.

The live unit-test command prints each case number out of eleven, its expected ruling, current workflow stage, and a PASS/FAIL result with ruling, refund, elapsed time and token count. Stage messages are flushed immediately while the review runs, including advocate analysis, Judge review, rebuttal, decision correction and final validation. Mandatory referrals skip agent stages. Failures print their validation issues and remain unittest failures; no artificial completion percentage is shown for individual model calls.

For repeated measurements and a saved report:

```bash
.venv/bin/python evaluation.py --live --runs 3 --output /tmp/fairride-live-regression.json
```

This CLI is a report generator, not a pass/fail regression gate; its exit status does not indicate that every case matched. Review case outcomes, autonomous resolution, operational failures and the saved model name. DISP-005, DISP-008 and DISP-009 are referred before model calls, so they exercise policy safeguards rather than model quality. Wording may vary across runs; exact prose is not compared. Automated checks validate schema, source existence, precedents and policy-constrained outputs, but do not fully establish factual support for every sentence. Inspect a sample of arguments/explanations manually, especially after changing models or prompts.

The tracked `evaluation_results.json` predates the supplied policy v2.1 migration. Its blanket-acceptance match rate must not be compared to the new accuracy definition. It is preserved as a historical run; no new paid evaluation was performed for this change.

The user supplied a separate live-test transcript on 14 October 2026: all eleven case checks passed, with Judge corrections on DISP-002, DISP-004 and DISP-011. Two mock-harness checks then failed because the skip attribute was absent in live-enabled mode; both were fixed and reverified without paid calls. The historical JSON was not replaced by that terminal transcript. Repeat runs and claim-support review are still needed.

## Regression coverage

`tests/test_evaluation_scoring.py` verifies correct and incorrect final rulings, clear/ambiguous escalation, missing credentials, model/schema/citation/amount failures, separate metric denominators, all-failed batches, empty summaries, and console N/A behavior.

## Pre-merge review — 14 October 2026

Three live runs of `qwen3.6:35b` passed 32 of 33 strict case checks. Nine checks were mandatory policy referrals with no model calls; 24 exercised the agents. One DISP-002 advocate response exceeded the 1500-character guard and was rejected. Eight Judge decisions required semantic correction; none of the accepted final refunds differed from their fixed expected amounts. All eleven hand-written example UI flows passed.

Full activity was captured locally to inspect rejected Judge responses and cited claims. The audit found incorrect prose even when the final decision was correct: DISP-004's Judge misstated its waiting timeline, DISP-010's advocate used the wrong billable distance, and route explanations retained contradictory intermediate calculations. Some advocates also invented contact obligations or misstated the justified-and-agreed route rule. These are response-quality blockers; PR #2 has not been merged.

The independent code review found and verified two fixes before these runs: safety phrases/app events must trigger referral, and wait-fact provenance must include the GPS evidence that caps physical waiting time. The public summary in `evaluations/pr2-review-2026-10-14.json` records outcomes, rejected structured decisions and source-linked prose findings without raw model discourse. The historical `evaluation_results.json` remains untouched.
