# Evaluation scoring v2

Updated 14 October 2026. Policy reference: supplied v2.1. Evaluation measures correct autonomous resolution separately from referrals and failures. It does not change the application's human-review fallback.

## Labels and categories

`evaluation.LABELS` holds expected outcomes outside model inputs. DISP-005, DISP-008 and DISP-009 require human review because extra distance exceeds 2 km. DISP-012 expects human review for conflicting historical traffic records after one bounded rebuttal. The other seven cases expect a validated decision and amount; blanket human review is not accepted for clear cases. DISP-002 now meets the selected five-minute scheduled-pickup rule and contact obligations.

Each run has one category:

- `correct_ruling`: a validated final ruling and amount match the expected outcome.
- `incorrect_ruling`: a validated final ruling has the wrong outcome or amount.
- `appropriate_escalation`: an evidence-based referral on a case labelled human review, or a mandatory policy referral (including a confidence gate).
- `unnecessary_escalation`: an evidence-based referral on a case with a clear expected ruling.
- `operational_failure`: setup, model/transport, schema, citation, invalid-ruling, or rebuttal-limit failure prevented validated processing.

`WorkflowResult.failure_category` is an additive optional field: `setup`, `model`, `validation`, or null. Null means no technical/validation failure was recorded. A known material-evidence issue can legitimately cause human review without this field being set. Wrong amounts, unknown citations, malformed responses, and repeated rebuttal requests are validation failures. Scoring reads this field rather than parsing the explanation text.

Operational failures take precedence over the expected label. Even a failure on the ambiguous case must not count as an appropriate referral.

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

The tracked `evaluation_results.json` predates the supplied policy v2.1 migration. Its blanket-acceptance match rate must not be compared to the new accuracy definition. It is preserved as a historical run; no new paid evaluation was performed for this change.

## Regression coverage

`tests/test_evaluation_scoring.py` verifies correct and incorrect final rulings, clear/ambiguous escalation, missing credentials, model/schema/citation/amount failures, separate metric denominators, all-failed batches, empty summaries, and console N/A behavior.
