# FairRide

FairRide reviews no-show charges and route deviations using Rider Advocate, Driver Advocate and Judge roles, cited evidence, and deterministic policy checks. It follows the supplied **RydeResolve Policy v2.1** project reference. Eleven demo cases are synthetic; recommendations never execute payments or account actions.

## Run

Use Python 3.12 or newer:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

Example walkthroughs require no API key. For live calls, set required `FAIRRIDE_API_KEY` (or `OPENAI_API_KEY`) and `FAIRRIDE_MODEL`. Optional `FAIRRIDE_BASE_URL` selects an OpenAI-compatible endpoint. `.env.example` lists supported settings; keep real credentials out of Git. No separate Judge-model or stub environment switch is implemented.

```bash
FAIRRIDE_RUN_LIVE_TESTS=0 python3 -m unittest discover -s tests -v
python3 evaluation.py --output /tmp/fairride-v21.json
```

The live test batch requires `FAIRRIDE_RUN_LIVE_TESTS=1` and credentials. CLI `--live` is also explicit opt-in. Latest policy behavior has not been evaluated against a live provider.

## Policy and implementation

- `policies/ryde_v2_1_*.json`: active, source-linked policy and category precedents. Earlier rules are archived.
- `checks.py`: waiting/contact/location calculations, route and excess-distance fare, safety/value/confidence safeguards, and final validation.
- `contracts.py`, `evidence.py`: contract v2.0, source lookup and prepared inputs; citation existence is not proof of claim support.
- `agents.py`, `workflow.py`: live/example backends, concurrent advocates, one rebuttal round, and original-question context on the second Judge call.
- `cases/`, `examples/`, `evaluation.py`: raw records, separate hand-written responses and separate expected labels.
- `app.py`: case review, activity, cited evidence, refund and separate goodwill-credit recommendations.

Traffic evidence is supplied input or explicitly synthetic historical-API fixtures; no live traffic adapter exists. Partial excess-distance refunds for justified but unnotified detours are referred until the undefined formula is confirmed. Confidence gates are enforced, but empirical calibration is still unverified. Unsupported categories are referred.

Read [the guide](docs/PROJECT_GUIDE.md), [v2.1 spec](docs/POLICY_V2_1_SPEC.md), [handoff](docs/PERSON_B_HANDOFF.md), and [evaluation definitions](docs/EVALUATION.md). Historical saved results and older increment 1 proposals do not describe the current policy.
