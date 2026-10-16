# Governing policy migration — v2.1

User decision, 14 October 2026: follow the supplied `data/Document 2 — Ryde Dispute Resolution Policy v2.1 (Markdown).md` as the project's governing reference. This is supplied project material, not independently verified public Ryde policy.

## Scope and rules

Migrate existing no-show and route categories. Apply shared safety, dispute-value, confidence, and fraud-flag escalation rules to every review. Other categories remain unsupported and are referred without a ruling. Do not execute refunds, credits, suspensions, or new external API calls.

- No-show: five-minute free wait from scheduled pickup; driver must be physically present and send at least one in-app message and make at least one in-app call before cancelling. Invalid fees must be reversed; `no_action` cannot retain them. Driver no-show plus no contact permits a separate SGD 5 goodwill-credit recommendation.
- Route: additional distance in km, tolerance at most 1 km. Unjustified excess distance is fully refundable as a component of the fare. Traffic must use route/time-matched historical traffic evidence, not a driver's assertion or an app-alert keyword. Timely notification and acknowledgment matter.
- Justified but unnotified route: user explicitly selected human review until its unspecified partial-refund formula is confirmed. Do not invent a percentage or infer one from a precedent amount.
- Route deviation above 2 km always requires human review; otherwise automated rulings require at least 0.80 confidence. Fraud flags on either party raise the requirement to 0.95; they do not establish fault. Amounts above SGD 50 and safety incidents require human review. SGD 10–50 requires at least 0.80 confidence.
- Include relevant supplied precedent clauses by dispute category, outside case labels. Require a relevant precedent citation in final rationale where supplied.

## Explicit interpretations

Five minutes is inclusive when the free-wait period ends. Early arrival gives no extra free-wait credit. For late arrivals, require five physical minutes at pickup after scheduled time as well; this conservative interpretation prevents billing time before arrival. Document it rather than claiming the source explicitly addresses late arrival.

Dispute value uses an explicit contested amount where supplied, otherwise the actual charge as a conservative bound. Mandatory safeguards are checked before any Judge ruling. Conflicting or unavailable traffic records are distinguished from an affirmative historical report of no congestion. Missing consent for a justified route is not assumed to be agreement.

## Interfaces and verification

Use versioned, source-linked `Policy` objects, risk gates in `ReviewInput`, typed goodwill/refund recommendations, and an explicit prior Judge assessment in the second call. Keep profile history out of agent input; expose only the fraud-derived confidence requirement. Model confidence remains self-reported; empirical calibration is a documented remaining limitation.

Acceptance: boundary/contact/credit tests; route distance, historical evidence and notification tests; policy escalation and confidence tests; no-action rejection; original-question context test; all examples and labels migrated; complete offline suite green; no live API calls. Setup and handoff examples must match current code.

Missing arrival metadata alone does not prove driver absence. Pickup GPS can establish arrival; an explicitly confirmed no-show or a known late arrival is needed for the separate goodwill credit. A recorded departure caps physical waiting time. Explicit refusal is never agreement, even if the message includes the word “agree.” A justified route with notification but no consent is referred because the source does not specify its disposition.

When a reported timely arrival conflicts with relevant pickup GPS and neither source establishes presence, the elapsed five-minute, no-contact case may leave goodwill entitlement unresolved even though contact failure already establishes fee reversal. Refer the overall dispute to reconcile that material conflict. Do not treat a computed zero credit as a settled denial, choose a source by an invented hierarchy, or create a referral for GPS recorded before the claimed arrival. Corroborating pickup presence must be relevant to the scheduled/reported arrival window; stale historical pings do not settle a current conflict.

Verified 14 October 2026: 65 offline tests pass, one live batch is skipped; all eleven example workflows match their labels (seven final decisions, four referrals). Live provider quality, confidence calibration and the Streamlit UI have not been verified for this migration.
