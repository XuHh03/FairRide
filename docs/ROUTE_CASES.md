# Route scenario coverage — 13 October 2026

All fixtures and route policy rules are synthetic. Examples are hand-written; expected outcomes live in `evaluation.py`, outside agent input.

| Case | Evidence | Expected outcome |
|---|---|---|
| DISP-005 | Significant 36.2% deviation; driver traffic claim lacks supporting alerts | Partial refund of SGD 6.93 |
| DISP-006 | 12.1% deviation, below the sample threshold | Uphold charge, zero refund |
| DISP-008 | Significant deviation; confirmed closure matches planned route and trip time | Uphold charge, zero refund |
| DISP-009 | Two closure snapshots disagree for the same route and validity period | One follow-up, then human review if conflict remains unresolved |

DISP-008/009 intentionally share route and fare assumptions with DISP-005 to isolate the effect of justification evidence. They are development contrasts, not held-out production accuracy evidence.

## Evidence and sample policy v1.1

App events of type `traffic_alert`, `road_closure`, or `rider_route_change` supply `affected_route_id`, `valid_from`, `valid_until`, and `status`. Validity is checked at the recorded trip start for these fixtures. The period is inclusive.

- `active`: positive supporting evidence when route and time match.
- `none`: negative evidence; never positive corroboration.
- `unknown`/`conflicting`, or simultaneous active/none snapshots of the same exception kind: material uncertainty requiring human review.
- A driver statement without corroboration does not justify significant deviation under this sample policy. Unsupported justification can yield a refund; conflicting evidence yields a referral.

`checks.route_justification` supplies the same rule to final validation. A confirmed exception permits retaining a significant-deviation fare and prevents a deviation refund. Structured snapshots are synthetic source records; arbitrary narrative words such as “traffic” do not establish confirmation.

## Fare corrections

DISP-005 now follows its existing rates:

- Charged: 3.50 base + 13.86 distance + 8.75 time + 0.50 booking = **26.61**.
- Estimated: 3.50 + 10.18 + 5.50 + 0.50 = **19.68**.
- Difference: **6.93**, or **693 cents**.

DISP-006's actual components already total 21.50. Its estimate at the stated rates is corrected to **17.90**, making its fare difference **3.60**. It remains below the deviation threshold and receives no refund.

Component amounts use half-up rounding to cents. Fare totals, trip fields, and displayed/system records are reconciled. Deterministic checks compare actual components, rate calculations, trip totals, and an explicitly supplied estimate breakdown. Derived fare facts resolve the real source IDs rather than assuming particular IDs.

Historical `evaluation_results.json` contains earlier fare values and scoring; generate a fresh report before comparing current outcomes.

## Integration and verification

- Both new cases appear in the Streamlit selector and batch evaluation.
- DISP-009 has case-specific, cited rebuttal examples referencing the conflicting alerts.
- `tests/test_route_scenarios.py` covers the new outcomes, refund rejection for a justified route, negative/irrelevant/out-of-period alerts, rider-requested exceptions, conflicting fare records, and provenance after source IDs change.
- The full suite has 70 offline passes and six skipped live tests. All eight example workflows match their categories: six final rulings and two appropriate referrals.
- No new live-model evaluation or UI execution was performed. Use `python3 evaluation.py --output /tmp/fairride-route-cases.json` for an offline integration run.

Remaining work for Person B: the no-show `no_action` gap and explicit previous-question context in the second Judge call identified in the progress review remain separate tasks.
