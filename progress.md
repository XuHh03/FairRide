# FairRide progress

Updated 5 October 2026. This is a repository-based status snapshot, not a claim that a live agent review has run.

## Done so far

- Initialized the Python/Streamlit prototype and project documentation (`README.md`, `docs/PROJECT_GUIDE.md`, and `docs/PERSON_B_HANDOFF.md`). Git history has the initial scaffold commit and a `.gitignore` update.
- Added one no-show dispute fixture, `cases/DISP-002.json`, with stable IDs on ticket, trip, GPS, chat, and app-event records. Retained the supplied source document in `data/`. Expected decisions are not embedded in the case JSON.
- Added `policies/sample_no_show.json` with six identified clauses and explicit sample-only status. The assumed wait clock starts at driver arrival; it is not a verified Ryde policy.
- Implemented case/policy loading, no-show wait-time and threshold calculations, Pydantic v2 input/output contracts, evidence and policy lookup, normalized agent input, and citation-existence checks.
- Added hand-written advocate/Judge output examples and tests for calculations, IDs, schema constraints, profile exclusion, and the configurable wait clock.
- Built a read-only Streamlit view of `DISP-002`, its calculated wait, sample policy, and raw records.

## Current state and verification

- `agents.py` has three typed role functions, and `workflow.py` has `run_review`; all still raise `NotImplementedError`. There are no live model calls, rebuttals, final rulings, refund actions, or activity-log UI.
- Only `DISP-002` and the no-show sample policy exist. Route deviation has no fixtures, policy, or calculation yet.
- `docs/PERSON_B_HANDOFF.md` reports nine passing tests in a configured environment. On this checkout, `python3 -m unittest discover -s tests -v` ran the two no-show tests successfully but could not import `test_shared_contract.py` because `pydantic` is not installed in the active Python environment. No local `.venv` is present. Install `requirements.txt`, then rerun the full suite.
- `checks.no_show_facts` reports an eight-minute wait from 08:43 to 08:51 and time-threshold eligibility for the sample case. This is only a time check, not a final fee ruling. `EVENT-008` says the fee became applicable after five minutes, conflicting with the sample policy's eight-minute threshold; pickup-entrance evidence also remains ambiguous.

## Next steps

1. **Get a green local baseline:** create a Python 3.12+ virtual environment, install `requirements.txt`, and run the full unit suite. Record any actual failures before changing interfaces.
2. **Complete the no-show review path:** connect a model client through configured secrets; implement both advocates and Judge using `ReviewInput`, `AdvocateResult`, and `JudgeResult`. Parse and check schemas and citations after every call.
3. **Implement `workflow.run_review`:** call both advocates, request at most one targeted rebuttal round, call the Judge again, keep a visible activity log, and return human review on invalid or unresolved material evidence. Agree on a question parameter for advocate rebuttals before changing their signatures.
4. **Add deterministic final checks:** validate policy conditions and evidence support, compute refund cents from the charged amount, and reject inconsistent rulings or amounts. Keep the `EVENT-008` conflict visible rather than changing source evidence.
5. **Complete the UI and coverage:** display arguments, citations, rebuttal, validation issues, and the final recommendation. Add contrasting no-show cases; then build route-deviation policy, records, calculations, and cases. Keep expected outcomes outside model input.
6. **Evaluate and prepare the demo:** use rider-favorable, driver-favorable, and ambiguous cases for both dispute types; record ruling, citation, arithmetic, abstention, latency, and cost results. Rehearse the live flow and prepare the required architecture and submission assets. The project guide lists a 16 October 2026 submission date and CodeBuddy/WorkBuddy development-conversation evidence requirement; verify current organizer instructions before submission.

## Key references

- `docs/PROJECT_GUIDE.md`: scope, architecture, evaluation, and submission plan.
- `docs/PERSON_B_HANDOFF.md`: implemented interfaces, exact policy assumptions, and team handoff.
- `agent.md`: working conventions for agents editing this repository.
