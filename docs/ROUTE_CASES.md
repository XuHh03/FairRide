# Route coverage under supplied policy v2.1

Updated 14 October 2026. Cases and historical traffic responses are synthetic development fixtures. The governing reference is the supplied policy in `data/`; it has not been independently verified as public Ryde policy.

| Case | Evidence | Expected result |
|---|---|---|
| DISP-005 | 6.7 km extra | Mandatory human review: above 2 km |
| DISP-006 | 2 km extra, historical report of no congestion | Refund excess-distance fare: SGD 1.10 |
| DISP-008 | 6.7 km extra, traffic justification | Mandatory human review: above 2 km |
| DISP-009 | 6.7 km extra, conflicting historical records | Mandatory human review before model calls |
| DISP-010 | 1.5 km extra, no congestion | Refund excess-distance fare: SGD 0.83 |
| DISP-011 | 1.5 km extra, congestion, timely notice and consent | Uphold charge |
| DISP-012 | 1.5 km extra, conflicting historical records | One rebuttal, then human review if unresolved |

Additional distance at most 1 km receives no refund. Automatic route decisions require additional distance at most 2 km and confidence at least 80%, or 95% with either party fraud-flagged. Shared safety and value gates also apply. An unjustified detour refunds only the extra distance charge, rounded half-up to cents; total fare differences and time charges are not the refund basis.

For a justified but unnotified detour, the user chose human review until the source's partial-refund formula is confirmed. A justified route without rider consent is also referred; consent is not inferred from a refusal.

`traffic_data` records must name the planned route, cover the deviation time, and identify a historical traffic API source (or explicitly marked fixture). `congested` supports justification; `no_congestion` does not. Missing, unknown or contradictory records remain uncertainty. App-alert keywords cannot substitute for historical traffic records. No live traffic API adapter exists.

Fare consistency checks still compare component sums, rates, distances, durations and supplied estimates. Source IDs remain stable and derived facts cite their actual source records. Expected answers remain in `evaluation.py`, outside model inputs.

Run `python3 evaluation.py --output /tmp/fairride-v21.json` for the eleven-case example batch. Seven decisions and four referrals match their labels. These hand-written examples do not measure live model accuracy. Earlier `evaluation_results.json` uses obsolete policy and scoring.
