# FairRide progress

Updated 15 October 2026. Current work follows the supplied v2.1 reference on the Person A integration branch.

## Current update

- Integrated merged PR #6 (`88e00dc`) with the three Person A commits. Dashboard and exports share the canonical final explanation; fact-value and length repairs share one correction budget; support-review schemas remain separate. Preserved both UI suites and fixed the unverified-wait checklist. Verified 161 passing tests and one skipped live batch. See `docs/PERSON_B_HANDOFF.md` for the resolution table and remaining issues: prose accuracy, combined live-provider validation and the undefined partial-refund formula.

- Demo priority: deterministic validation and the grounded final explanation remain active; experimental model support checks are now opt-in with `FAIRRIDE_CHECK_ARGUMENT_SUPPORT=1` and off by default. Added explicit missing-message, inclusive five-minute arrival and 2 km boundary checks, plus explanation coverage across all eleven demos and separate goodwill/refund amounts. No extra paid tests are needed to verify these deterministic changes.
- Before PR #6 integration: 139 tests ran (138 passed, one live batch skipped). Policy/explanation and response-retry commits were also verified independently from their staged snapshots before committing.

- When explicitly enabled, live initial/rebuttal advocate outputs receive bounded model support reviews before the Judge, with one semantic rewrite and recheck. Persistent unsupported output stops as an operational failure. UI logs preserve originals, findings and corrections. Positive supported verdicts do not trigger correction; review-format/citation repair remains bounded and audit usage is included in evaluation totals.
- Earlier support-check verification: 133 offline tests ran (132 passed, one live batch skipped). Revised checker live checks passed 3/4, followed by a 2/2 targeted follow-up; one earlier Judge-format failure and an escaped DISP-003 timestamp error remain documented. Issue #5 remains open for accuracy, despite improved screening. See `evaluations/argument-review-2026-10-15.json`.

- Issues #3 and #4 are implemented locally: completed reviews show an application-generated rationale while preserving original Judge prose, and overlong statements share the existing single schema/citation retry. Independent review fixes prevent unverified pickup presence and boundary notification from being overstated.
- Issue #5 has explicit advocate rules, per-case computed policy context and UI labels/source inspection. Its accuracy work remains open: the latest audit still found unsupported advocate prose in DISP-003, DISP-004 and DISP-011. The latest checks ran 123 offline tests (122 passed, one live batch skipped), plus a separate 11/11 live batch and 4/4 targeted follow-up. Correct structured decisions are not proof of prose accuracy. See `evaluations/issues-3-5-review-2026-10-14.json`.


- 15 October: added `review_summary.py` and a reviewer-first Streamlit result screen with deterministic decision reasons, cited policy checklist, wait/distance/fare calculations, chronological evidence timeline and JSON report download. Agent activity is collapsed and labelled as commentary. Route metrics now show additional km and the excess-distance component. Exports omit raw profiles; referrals and failures carry no recommended amount.
- Added optional structured fact assertions on claims and Judge outputs, checked against supplied Python facts with the existing shared one-response correction budget. Wrong known assertions cannot be hidden by dropping them during correction. Added timestamp and arrival facts without renumbering existing fact IDs and narrowed derived-fact provenance. Legacy outputs may omit assertions; arbitrary free-text semantics remain unverified.
- The dashboard now places case selection, review mode, run/export controls and four-view navigation in a sidebar. Overview shows the decision, key metrics, compact checklist and calculations, plus a route-distance chart against the tolerance and AI limit. Evidence, Agent activity and Sources & policy have dedicated views; citation popovers open records without changing views. Navigation preserves results and makes no agent calls; a new review returns to Overview.
- PR #6 verification before integration: 128 tests passed and one live batch skipped, including all eleven cases across all dashboard views and regressions for recorded wait/arithmetic defects, contact timing, arrival boundaries, citation records and report export. Example evaluation remains seven correct rulings and four appropriate referrals. No new live calls were made; explicitly rerun live evaluation after these prompt/schema changes before reassessing model response quality.
- Active source-linked v2.1 policies replace archived sample policies. No-show fees require five physical minutes no earlier than scheduled pickup, verified presence, and both message and call. Invalid charges cannot survive as `no_action`; goodwill credit is separate and requires evidence of driver no-show.
- Route refunds use additional kilometres and excess-distance fare. Historical traffic, timely notification and consent are checked separately. Justified unnotified detours are referred until the partial formula is confirmed.
- Shared safety, value, route-distance and fraud/confidence gates prevent prohibited rulings. Missing consent and explicit refusal never count as agreement. Repeated no-show history flags manual account review without executing restrictions.
- Contract v2.0 adds confidence and refund/credit fields. The second Judge receives its original assessment and question; Python allows one rebuttal round.
- Live-response handling now resolves declared fact citations to their recorded sources, shares one schema/citation correction retry, and permits one Judge policy-validation correction on clear cases. Persistent response errors are distinguished from evidence-based referrals. Statements have a 1500-character runaway guard; prompts focus on distinct material points without imposing a sentence count.
- The Streamlit app shows live workflow progress, corrections and citation mappings. Regression tests print case/stage progress and compare exact rulings, refunds, credits and bases against fixed labels outside model input.
- 14 October verification: 109 offline tests passed, one live batch skipped; all eleven example UI flows passed. After an earlier user-run all-pass batch, three new `qwen3.6:35b` runs passed 32/33 checks. Nine were policy-only referrals and 24 exercised agents. DISP-002 failed its length guard once; eight Judge responses were corrected. No incorrect accepted final amounts were found, but the prose audit found incorrect wait times, invented obligations and conflicting arithmetic. The saved review held PR #2 pending response-quality work. See `evaluations/pr2-review-2026-10-14.json`.
- Pre-merge review fixed two verified defects: safety indicators such as car accidents, threats and explicit app safety events now refer before agent calls; the wait fact cites consumed GPS evidence and accurately describes the departure cap.
- Setup and Person B handoff reflect actual interfaces. Remaining: inspect factual support and initial Judge errors, repeat live evaluation for consistency, confirm partial-refund formula and confidence calibration, and add real historical traffic integration if required.
- Read `docs/POLICY_V2_1_SPEC.md`, `docs/EVALUATION.md` and `docs/ROUTE_CASES.md`. Saved evaluation results and the historical notes below describe earlier behavior.

## Historical snapshot — 5 October 2026

The sections below describe the earlier implementation, before the current additions.

## Done so far

- Initialized the Python/Streamlit prototype and project documentation (`README.md`, `docs/PROJECT_GUIDE.md`, and `docs/PERSON_B_HANDOFF.md`). Git history has the initial scaffold commit and a `.gitignore` update.
- Added one no-show dispute fixture, `cases/DISP-002.json`, with stable IDs on ticket, trip, GPS, chat, and app-event records. Retained the supplied source document in `data/`. Expected decisions are not embedded in the case JSON.
- Added `policies/sample_no_show.json` with six identified clauses and explicit sample-only status. The assumed wait clock starts at driver arrival; it is not a verified Ryde policy.
- Implemented case/policy loading, no-show wait-time and threshold calculations, Pydantic v2 input/output contracts, evidence and policy lookup, normalized agent input, and citation-existence checks.
- Added hand-written advocate/Judge output examples and tests for calculations, IDs, schema constraints, profile exclusion, and the configurable wait clock.
- Built a Streamlit review screen for `DISP-002` with example/live modes, cited source records, agent activity, timing, token usage, and result.
- Implemented a configurable chat-completions client, three agent roles, a hand-written example backend, parallel initial advocate calls, one optional rebuttal round, and conservative human-review fallback.
- Added deterministic final checks for the known timer conflict, missing designated entrance, sample-policy status, citations, and refund amount. Added workflow and mocked-client tests.

## Current state and verification

- The example walkthrough runs end to end and refers `DISP-002` to human review after one rebuttal. A synthetic resolvable-case test reaches a validated final ruling. The live client request is tested with a mocked HTTP response; provider compatibility, real model quality, cost, and latency remain unverified because no API credentials are configured.
- Only `DISP-002` and the no-show sample policy exist. Route deviation has no fixtures, policy, or calculation yet.
- A local Python 3.12.13 `.venv` has `requirements.txt` installed (`pydantic` 2.13.5 and `streamlit` 1.65.0). `.venv/bin/python -m unittest discover -s tests -v` passes all 16 tests. Streamlit's `AppTest` opens the app and runs the example walkthrough without UI exceptions. The virtual environment is ignored by Git.
- `checks.no_show_facts` reports an eight-minute wait from 08:43 to 08:51 and time-threshold eligibility for the sample case. This is only a time check, not a final fee ruling. `EVENT-008` says the fee became applicable after five minutes, conflicting with the sample policy's eight-minute threshold; pickup-entrance evidence also remains ambiguous.

## Next steps

1. **Verify live operation:** configure a permitted provider, run `DISP-002`, and inspect JSON-mode compatibility, citations, latency, and token usage. Update prompts or client behavior based on observed responses; keep uncertain outcomes in human review.
2. **Broaden no-show coverage:** add rider-favorable, driver-favorable, and ambiguous cases with independent expected answers. Strengthen semantic support checks; current code checks citation existence and known material conditions, not every natural-language inference.
3. **Add the second dispute type:** design a sample route-deviation policy, fixtures, deterministic route/fare facts, checks, and case selection in the UI.
4. **Evaluate and prepare the demo:** record rulings, citation support, arithmetic, abstention, latency, and cost across both categories. Rehearse the live flow and prepare architecture and submission assets. The project guide lists a 16 October 2026 submission date and CodeBuddy/WorkBuddy development-conversation evidence requirement; verify current organizer instructions before submission.

## Key references

- `docs/PROJECT_GUIDE.md`: scope, architecture, evaluation, and submission plan.
- `docs/PERSON_B_HANDOFF.md`: implemented interfaces, exact policy assumptions, and team handoff.
- `agent.md`: working conventions for agents editing this repository.
