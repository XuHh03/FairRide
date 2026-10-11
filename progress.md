# FairRide progress

Updated 5 October 2026. This is a repository-based status snapshot. The example workflow has run locally; a live model provider has not been called.

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
