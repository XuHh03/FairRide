# FairRide

FairRide is a Streamlit prototype for evidence-based rider–driver dispute review in the Tencent Cloud hackathon Digital Native track. It currently supports one sample no-show case, `DISP-002`. The policy is synthetic and **not an official Ryde policy**. The review recommends an outcome or human referral; it never issues a payment.

The app has two clearly labeled modes. **Example walkthrough** runs hand-written agent responses through the real controller and validation, with no API key. **Live model** calls an OpenAI-compatible chat completions endpoint; it requires configuration and has not been verified against a live provider in this repository. For `DISP-002`, the supplied app event conflicts with the sample policy and the physical pickup entrance is unresolved, so the example correctly ends in human review.

## Run locally

Use Python 3.12 or newer:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

Run tests:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

To enable **Live model**, set `FAIRRIDE_API_KEY` (or `OPENAI_API_KEY`) and `FAIRRIDE_MODEL`. `FAIRRIDE_BASE_URL` defaults to `https://api.openai.com/v1`; set it for another compatible provider. The client sends JSON-mode chat completion requests. Keep credentials in environment variables or deployment secrets, never in the repository. Model latency and token counts appear in the activity log when the provider returns usage data.

## Project map

| Path | Purpose |
|---|---|
| `app.py` | Case review, activity log, cited sources, timing, and result |
| `case_data.py` | Load case and sample-policy fixtures |
| `contracts.py` | Pydantic input/output schemas and valid actions |
| `evidence.py` | Source lookups, normalized agent input, and citation-existence checks |
| `checks.py` | No-show facts, known material conflicts, and ruling/amount checks |
| `agents.py` | Live model backend and hand-written example backend |
| `workflow.py` | Parallel initial advocates, Judge, one rebuttal round, validation, and referral |
| `cases/`, `policies/` | One no-show case and explicit sample policy |
| `tests/` | Calculation, contract, workflow, and client-shape tests |
| `examples/` | Hand-written agent output fixtures, never AI decisions |
| `data/` | Supplied original document, retained for reference only |

`evidence.validate_references` checks whether IDs exist, not whether a statement is true. The final checks catch specific known conflicts and amount errors; they are not a general proof of evidence support. Rider and driver history is excluded from model input and must not determine fee validity.

See [the project guide](docs/PROJECT_GUIDE.md), [the shared handoff](docs/PERSON_B_HANDOFF.md), and [progress](progress.md) for design decisions, interfaces, and next steps. Route-deviation cases and evaluation are still to be built.
