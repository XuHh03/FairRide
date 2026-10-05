# FairRide

Initial scaffold for the Tencent Cloud hackathon Digital Native track: a rider–driver dispute review prototype. The current app displays one no-show case and calculated wait-time facts. Agent calls, rebuttals, rulings, and the second dispute type remain to be implemented.

See [the project guide](docs/PROJECT_GUIDE.md) for the architecture, agent flow, evidence references, team split, and submission plan.

The shared input/output schemas, evidence lookup, and sample outputs are implemented. Start with [Person B's handoff](docs/PERSON_B_HANDOFF.md) for exact interfaces, policy assumptions, a runnable example, and remaining work. The examples are hand-written contract fixtures, not AI decisions.

## Run locally

Use Python 3.12 or newer:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

Run the current checks without extra test packages:

```bash
python3 -m unittest discover -s tests -v
```

## Project map

| Path | Purpose |
|---|---|
| `app.py` | Case review screen |
| `case_data.py` | Load case and policy fixtures |
| `contracts.py` | Shared Pydantic input/output schemas and valid actions |
| `evidence.py` | Source lookups, normalized agent input, and citation checks |
| `checks.py` | Deterministic facts and, later, ruling validation |
| `agents.py` | Rider Advocate, Driver Advocate, and Judge model calls (placeholders) |
| `workflow.py` | Agent order and one-round rebuttal limit (placeholder) |
| `cases/` | Raw case evidence, without the expected answer |
| `policies/` | Explicitly labelled sample policy |
| `tests/` | Checks against hand-verified case facts |
| `examples/` | Hand-written advocate and Judge contract fixtures |
| `data/` | Original supplied sample document, retained as reference |

`policies/sample_no_show.json` is a **sample policy**, not an official Ryde policy. It starts the wait clock at recorded driver arrival, following the sample app events. Confirm the real policy and clock rule before presenting a production claim. Rider and driver history must not determine whether this individual cancellation fee is valid.

## Next implementation steps

1. Add model calls and validated evidence citations to the three functions in `agents.py`.
2. Implement the provisional Judge review, one rebuttal round, and final decision in `workflow.py`.
3. Add a contrasting no-show case and route-deviation cases, then show the complete activity log in `app.py`.

Use CodeBuddy or WorkBuddy during development and save at least three conversation screenshots for the hackathon submission.
