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

1. Follow the supplied project policy v2.1 and `docs/POLICY_V2_1_SPEC.md`; archived samples and older increment1 proposals are not governing instructions.
2. Use contractv2.0 and the interfaces in `docs/PERSON_B_HANDOFF.md`. The second Judge receives its prior assessment/question and an exhausted rebuttal budget.
3. Preserve raw source IDs. Source citations may include historical `TRAFFIC-*`; policy IDs identify exact sections and precedents. Do not cite computed FACT-* records as raw evidence.
4. Keep expected labels, original answer-bearing sample documents and raw profile history out of agent input. The required confidence reflects fraud flags; flags affect review thresholds, not fault. Verified rolling no-show records may recommend account review without executing restrictions.
5. Five-minute no-show eligibility also needs verified pickup presence, a message and a call before cancellation. Neither no_action nor another outcome may retain an invalid charge.
6. Route rules use additional kilometres and excess-distance fare, historical traffic and timely notification/agreement. Mandatory policy referrals must precede Judge rulings. Do not invent the unspecified partial-refund percentage.
7. Validate schemas, sources, policy conditions, integer refund/credit amounts and escalation gates. Source existence alone does not establish semantic support. Show cited outputs, not hidden reasoning.
8. No actual payments, credits, suspensions or live API calls without authorization. Standard tests must not call providers; live tests require explicit opt-in.

## Immediate work

Review the migration and current limitations, then configure/rehearse the UI and explicitly evaluate a live provider. Refer to `progress.md` for the current state.
