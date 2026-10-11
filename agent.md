# FairRide agent guide

Read this before changing the repository. The current project is a Python/Streamlit prototype for evidence-based rider–driver dispute review. The detailed design is in `docs/PROJECT_GUIDE.md`; exact shared interfaces and policy assumptions are in `docs/PERSON_B_HANDOFF.md`. Check `progress.md` for the current implementation status.

## Run and verify

- Use Python 3.12 or newer. Install `requirements.txt` in a virtual environment.
- Run the app with `.venv/bin/python -m streamlit run app.py`.
- Run tests with `.venv/bin/python -m unittest discover -s tests -v`.
- Keep generated files, API keys, and local secrets out of Git. Use environment variables or deployment secrets for model credentials.

## Repository map

- `app.py`: Streamlit review screen with example/live modes, agent activity, citations, and result.
- `case_data.py`, `cases/`, `policies/`: JSON fixture and sample-policy loading.
- `checks.py`: deterministic no-show facts, known material conflicts, and final ruling/amount checks.
- `contracts.py`: Pydantic v2 contract v1.0 for review input, advocates, Judge, and workflow result.
- `evidence.py`: stable source-ID lookup, normalized `ReviewInput`, and citation-existence checks.
- `agents.py`, `workflow.py`: live/example agent backends and the one-round review controller.
- `examples/agent_outputs.json`: hand-written schema examples, not model outputs or expected rulings.
- `tests/`: no-show calculations and shared-contract checks.

## Implementation rules

1. Preserve the public function signatures in `docs/PERSON_B_HANDOFF.md` unless the team updates the contract, examples, documentation, and tests together. If splitting `agents.py`, replace it with an `agents/` package; do not keep competing module and package implementations.
2. Keep raw case evidence and expected evaluation answers separate. Send agents `evidence.build_review_input(case, policy)`, which excludes rider and driver profile history. Do not send the original sample document or answer labels to a model.
3. Preserve explicit source IDs when editing case records. New records need unused IDs. Cite source and policy IDs, not derived `FACT-*` IDs, in agent claims. Validate every parsed agent response with the Pydantic contract and `evidence.validate_references`.
4. Citation existence does not establish that a claim is true. Check decisive claims against source content, sample-policy conditions, and Python-calculated amounts. Refer material missing or contradictory facts to human review.
5. Treat `policies/sample_no_show.json` as a synthetic policy, never an official Ryde rule. Its wait clock starts at recorded driver arrival; the five-minute free wait and eight-minute no-show threshold are distinct. `EVENT-008` conflicts with that threshold. Preserve and surface the conflict.
6. Do not use ratings, dispute counts, or fraud flags to decide this individual fee. GPS locates the recorded driver position but does not prove the rider's position or the designated entrance.
7. `proposed_action.amount_cents` is an integer SGD refund recommendation. Calculate and validate money in Python using integer cents or `Decimal`; model output must not execute a payment. Limit rebuttal to one round and show visible agent actions and cited outputs, not hidden reasoning.

## Immediate work

Evaluate the live model path with an actual provider, then add contrasting no-show cases and route-deviation support. The example walkthrough is hand-written and must never be described as a model result. See `progress.md` for the ordered work and current verification status.
