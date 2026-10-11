# FairRide — Technical Spec: Increment 1

**Increment:** No-show end-to-end loop
**Status:** Proposed — 11 October 2026
**Prerequisite:** Read `docs/PERSON_B_HANDOFF.md` and `docs/PRODUCT_SPEC_INCREMENT_1.md` first. This spec assumes the shared contracts (`contracts.py` v1.0), evidence system (`evidence.py`), and no-show facts (`checks.py`) are implemented and tested.

---

## 1. Target file structure

Migrate `agents.py` (module) into an `agents/` (package). The handoff warns: do not create both the same-named module and package as competing implementations.

```
agents/
  __init__.py     # re-exports public functions for backward compatibility
  client.py       # model API connection (new)
  advocates.py    # Rider + Driver Advocate prompts and calls (from agents.py)
  judge.py        # Judge prompt and call (from agents.py)
```

**Migration steps:**
1. `git rm agents.py` (or `rm` if no commit yet).
2. `mkdir agents && touch agents/__init__.py`.
3. Move advocate stubs to `agents/advocates.py`, judge stub to `agents/judge.py`.
4. `agents/__init__.py` re-exports so existing `from agents import rider_advocate` still works:

```python
# agents/__init__.py
from agents.advocates import rider_advocate, driver_advocate
from agents.judge import judge

__all__ = ["rider_advocate", "driver_advocate", "judge"]
```

**Other files changed in this increment:**

| File | Change |
|---|---|
| `agents/client.py` | New — model connection |
| `agents/advocates.py` | New — advocate prompts + calls |
| `agents/judge.py` | New — judge prompt + call |
| `workflow.py` | Implement `run_review` |
| `checks.py` | Add `validate_amounts` (amount policy checks) |
| `app.py` | Add "Run review" button + result panel |
| `requirements.txt` | Add `openai` |
| `.env.example` | New — documents required env vars |
| `tests/test_workflow.py` | New — workflow integration tests |

---

## 2. Model client (`agents/client.py`)

### Design

A single OpenAI-compatible client. TokenHub and OpenAI both speak the OpenAI Chat Completions API, so one client covers both. Configuration is entirely env-var driven; no keys in the repo.

```python
# agents/client.py
"""One model API connection. Reads config from env vars; no keys in the repo."""

import json
import os
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ["FAIRRIDE_API_KEY"],
            base_url=os.environ.get("FAIRRIDE_BASE_URL"),  # None = OpenAI default
        )
    return _client


def call_model(
    system_prompt: str,
    user_message: str,
    response_model: type[T],
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2000,
) -> T:
    """Call the model and parse the response into a Pydantic model.

    Uses JSON mode for structured output. The system prompt must instruct
    the model to return valid JSON matching the schema.

    Raises ModelCallError on parse failure or API error.
    """
    client = get_client()
    resolved_model = model or os.environ.get("FAIRRIDE_MODEL", "gpt-4o-mini")
    schema = response_model.model_json_schema()

    response = client.chat.completions.create(
        model=resolved_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    try:
        return response_model.model_validate_json(raw)
    except ValidationError as exc:
        raise ModelCallError(
            f"Model returned invalid JSON for {response_model.__name__}.\n"
            f"Raw: {raw[:500]}\nError: {exc}"
        ) from exc


class ModelCallError(Exception):
    """Raised when a model response cannot be parsed or validated."""
```

### Configuration

| Env var | Required | Default | Purpose |
|---|---|---|---|
| `FAIRRIDE_API_KEY` | Yes | — | API key for the model provider |
| `FAIRRIDE_BASE_URL` | No | OpenAI default | Override for TokenHub or other OpenAI-compatible endpoint |
| `FAIRRIDE_MODEL` | No | `gpt-4o-mini` | Model name for all agent roles |
| `FAIRRIDE_JUDGE_MODEL` | No | Same as `FAIRRIDE_MODEL` | Optional stronger model for the Judge role |

`.env.example`:
```
FAIRRIDE_API_KEY=sk-your-key-here
FAIRRIDE_BASE_URL=https://api.openai.com/v1
FAIRRIDE_MODEL=gpt-4o-mini
# FAIRRIDE_JUDGE_MODEL=gpt-4o
```

### Stub mode

For development without an API key, the client supports a `FAIRRIDE_STUB=1` env var that returns hand-written outputs from `examples/agent_outputs.json` instead of calling the model. This lets the workflow and UI be developed and tested without cost.

```python
def call_model(system_prompt, user_message, response_model, **kwargs):
    if os.environ.get("FAIRRIDE_STUB"):
        return _stub_response(system_prompt, user_message, response_model)
    # ... real call as above
```

`_stub_response` loads `examples/agent_outputs.json` and returns the matching example based on the role inferred from the system prompt. For rebuttal calls (question present), it returns a minimal valid `AdvocateResult`.

---

## 3. Advocate prompts (`agents/advocates.py`)

### Signature

```python
def rider_advocate(review: ReviewInput, question: str | None = None) -> AdvocateResult:
    ...

def driver_advocate(review: ReviewInput, question: str | None = None) -> AdvocateResult:
    ...
```

The `question` parameter extends the initial signature from the handoff. When `None`, the advocate builds its initial case. When provided, the advocate answers the Judge's specific question using existing evidence only.

### Rider Advocate system prompt

```
You are the Rider Advocate in a ride-hailing dispute resolution system for Ryde Singapore.

YOUR ROLE
Represent the rider's interests by building a fact-based case from the supplied evidence and policy.

RULES
1. You see the same evidence and policy as the Driver Advocate. You do not have access to any information not in the supplied records.
2. Every claim and counterpoint must cite at least one evidence_id or policy_id from the supplied records. A claim with no citation is invalid.
3. Use "claims" for arguments that support the rider's position. Use "counterpoints" for records that weaken the rider's case — acknowledge them honestly; hiding them from the Judge is not advocacy.
4. If the supplied records do not establish a fact, list it in "unanswered_questions". Do not speculate.
5. Do not use rider or driver profiles (ratings, dispute history, fraud flags, account age) as the basis for any claim. You may acknowledge they exist in the raw case, but you must not rely on them. They are excluded from your input.
6. Do not invent evidence IDs. Only cite IDs that appear in the supplied records.
7. Be concise: 1-3 claims, 1-2 counterpoints, 1-2 unanswered questions.

OUTPUT
Return a JSON object matching this schema:
{schema}

The "role" field must be "rider_advocate".
```

### Driver Advocate system prompt

Identical structure, with:
- `role` = `"driver_advocate"`
- "Represent the driver's interests..."
- Claims support the driver; counterpoints acknowledge rider-favorable records.

### Rebuttal prompt (when `question` is provided)

Append to the system prompt:

```
FOLLOW-UP QUESTION FROM THE JUDGE
{question}

Answer this specific question using only the existing evidence. Do not introduce new records. If the records do not answer it, say so in "unanswered_questions". Return your response as an AdvocateResult with the same schema.
```

### User message construction

```python
def _build_user_message(review: ReviewInput, question: str | None = None) -> str:
    parts = [
        f"Case: {review.case_id}",
        f"Dispute type: {review.dispute_type}",
        "",
        "EVIDENCE RECORDS (cite by id):",
        review.model_dump_json(indent=2),
    ]
    if question:
        parts.extend(["", "JUDGE'S QUESTION:", question])
    parts.extend([
        "",
        "Return a JSON object matching the AdvocateResult schema.",
    ])
    return "\n".join(parts)
```

### Implementation

```python
# agents/advocates.py
import json
from contracts import AdvocateResult, ReviewInput
from agents.client import call_model

_RIDER_SYSTEM = """..."""  # as above
_DRIVER_SYSTEM = """..."""

_SCHEMA = AdvocateResult.model_json_schema()


def rider_advocate(review: ReviewInput, question: str | None = None) -> AdvocateResult:
    user = _build_user_message(review, question)
    system = _RIDER_SYSTEM.format(schema=json.dumps(_SCHEMA, indent=2))
    if question:
        system += _REBUTTAL_SUFFIX.format(question=question)
    return call_model(system, user, AdvocateResult)


def driver_advocate(review: ReviewInput, question: str | None = None) -> AdvocateResult:
    user = _build_user_message(review, question)
    system = _DRIVER_SYSTEM.format(schema=json.dumps(_SCHEMA, indent=2))
    if question:
        system += _REBUTTAL_SUFFIX.format(question=question)
    return call_model(system, user, AdvocateResult)
```

---

## 4. Judge prompt (`agents/judge.py`)

### Signature

```python
def judge(
    review: ReviewInput,
    rider_argument: AdvocateResult,
    driver_argument: AdvocateResult,
    rebuttals: list[AdvocateResult] | None = None,
) -> JudgeResult:
    ...
```

Unchanged from the existing `agents.py` stub.

### Judge system prompt

```
You are the Judge in a ride-hailing dispute resolution system for Ryde Singapore.

YOUR ROLE
Weigh the evidence from both advocates, apply the policy, and issue one of three actions.

ACTIONS
1. "request_rebuttal" — You need a specific piece of evidence clarified. Ask one precise question directed to one or both advocates. This may happen at most once per case.
2. "final_ruling" — The evidence is sufficient. Issue a ruling and a proposed action.
3. "human_review" — Material facts remain unresolved. Refer the case for human review.

RULES
1. You see the original evidence, derived facts, policy, and both advocates' arguments.
2. Every ruling or explanation must cite at least one evidence_id or policy_id.
3. If the designated pickup entrance, rider location, or any material fact is not established by the records, do not assume it. Either request a rebuttal or refer to human review.
4. If two records conflict (e.g., an event description vs. a policy threshold), acknowledge the conflict in your explanation and cite both.
5. Do not use rider or driver profiles (ratings, dispute history, fraud flags) as the basis for your ruling.
6. Do not invent evidence IDs.
7. "proposed_action.amount_cents" is the refund to the rider in SGD cents (integer), not the original charge.
   - "uphold_charge" or "no_action": amount_cents must be 0.
   - "reverse_charge": amount_cents must equal the charged amount.
   - "partial_refund": amount_cents must be positive and less than the charged amount.
   Python will verify these; do not set them arbitrarily.
8. "confidence" (0.0 to 1.0) is your self-assessed certainty. It is displayed as context and cannot override evidence or policy checks.

OUTPUT
Return a JSON object matching this schema:
{schema}

If you are requesting a rebuttal, set action="request_rebuttal", provide a "question" and "rebuttal_roles", and leave ruling/proposed_action empty.
If you are issuing a final ruling, set action="final_ruling", provide "ruling" and "proposed_action", and leave question/rebuttal_roles empty.
If you are referring to human review, set action="human_review", provide an "explanation", and leave ruling/proposed_action/question/rebuttal_roles empty.
```

### User message construction

```python
def _build_judge_user_message(
    review: ReviewInput,
    rider: AdvocateResult,
    driver: AdvocateResult,
    rebuttals: list[AdvocateResult] | None,
) -> str:
    parts = [
        f"Case: {review.case_id}",
        f"Dispute type: {review.dispute_type}",
        "",
        "EVIDENCE AND DERIVED FACTS:",
        review.model_dump_json(indent=2),
        "",
        "RIDER ADVOCATE ARGUMENT:",
        rider.model_dump_json(indent=2),
        "",
        "DRIVER ADVOCATE ARGUMENT:",
        driver.model_dump_json(indent=2),
    ]
    if rebuttals:
        parts.extend(["", "REBUTTAL RESPONSES:"])
        for r in rebuttals:
            parts.append(r.model_dump_json(indent=2))
    parts.extend(["", "Return a JSON object matching the JudgeResult schema."])
    return "\n".join(parts)
```

### Implementation

```python
# agents/judge.py
import json
import os
from contracts import AdvocateResult, JudgeResult, ReviewInput
from agents.client import call_model

_JUDGE_SYSTEM = """..."""

_SCHEMA = JudgeResult.model_json_schema()


def judge(review, rider_argument, driver_argument, rebuttals=None):
    system = _JUDGE_SYSTEM.format(schema=json.dumps(_SCHEMA, indent=2))
    user = _build_judge_user_message(review, rider_argument, driver_argument, rebuttals)
    model = os.environ.get("FAIRRIDE_JUDGE_MODEL") or None
    return call_model(system, user, JudgeResult, model=model)
```

---

## 5. Rebuttal protocol

The rebuttal is a controlled, one-round exchange:

```
Judge (pass 1) → action = "request_rebuttal"
  ├── question: "Do the records identify a designated physical pickup entrance?"
  └── rebuttal_roles: ["rider_advocate", "driver_advocate"]

Workflow routes the question to each named role:
  ├── rider_advocate(review, question=judge.question) → AdvocateResult
  └── driver_advocate(review, question=judge.question) → AdvocateResult

Judge (pass 2) → receives rebuttals, issues final_ruling or human_review
```

**Hard limits (enforced in workflow):**
- At most one rebuttal round. If the second Judge call also returns `request_rebuttal`, the workflow overrides the status to `human_review` and logs: `"Rebuttal limit reached; second request rejected."`
- Advocates may only cite existing evidence IDs in rebuttals. They may not invent new records.
- The Judge's question must be non-blank and directed to at least one role (enforced by the contract validator).

---

## 6. Workflow controller (`workflow.py`)

### Logic

```python
def run_review(case: dict, policy: dict) -> WorkflowResult:
    """Run the full agent pipeline for one case.

    Steps:
    1. Prepare ReviewInput (evidence + policy + derived facts).
    2. Call both advocates.
    3. Validate advocate citations.
    4. Call the Judge.
    5. If Judge requests rebuttal: route question, collect responses, call Judge again.
    6. Validate the final result: citations + amounts + policy conditions.
    7. Build WorkflowResult with activity log.
    """
```

### Pseudocode

```python
def run_review(case, policy):
    log = ActivityLog()
    issues = []

    # 1. Prepare input
    review = build_review_input(case, policy)
    log.add("system", "review_prepared", {"case_id": review.case_id,
            "evidence_count": len(review.evidence),
            "fact_count": len(review.facts)})

    # 2. Call advocates
    try:
        rider = rider_advocate(review)
        log.add("rider_advocate", "initial_argument", rider.model_dump(mode="json"))
    except ModelCallError as exc:
        issues.append(f"Rider Advocate call failed: {exc}")
        return _human_review_result(review.case_id, log, issues)

    try:
        driver = driver_advocate(review)
        log.add("driver_advocate", "initial_argument", driver.model_dump(mode="json"))
    except ModelCallError as exc:
        issues.append(f"Driver Advocate call failed: {exc}")
        return _human_review_result(review.case_id, log, issues)

    # 3. Validate advocate citations
    issues += validate_references(rider, case, policy)
    issues += validate_references(driver, case, policy)

    # 4. Call Judge (pass 1)
    try:
        result = judge(review, rider, driver)
        log.add("judge", "first_pass", result.model_dump(mode="json"))
    except ModelCallError as exc:
        issues.append(f"Judge call failed: {exc}")
        return _human_review_result(review.case_id, log, issues)

    issues += validate_references(result, case, policy)

    # 5. Rebuttal (at most once)
    if result.action == "request_rebuttal":
        rebuttals = []
        for role in result.rebuttal_roles:
            fn = rider_advocate if role == "rider_advocate" else driver_advocate
            try:
                r = fn(review, question=result.question)
                log.add(role, "rebuttal_response", r.model_dump(mode="json"))
                issues += validate_references(r, case, policy)
                rebuttals.append(r)
            except ModelCallError as exc:
                issues.append(f"{role} rebuttal failed: {exc}")

        # Judge pass 2
        try:
            result = judge(review, rider, driver, rebuttals=rebuttals)
            log.add("judge", "second_pass", result.model_dump(mode="json"))
        except ModelCallError as exc:
            issues.append(f"Judge second pass failed: {exc}")
            return _human_review_result(review.case_id, log, issues)

        issues += validate_references(result, case, policy)

        # Enforce one-round limit
        if result.action == "request_rebuttal":
            issues.append("Rebuttal limit reached; second request overridden to human_review.")
            log.add("system", "rebuttal_limit_enforced", {})
            # Construct a human_review JudgeResult from the existing one
            result = JudgeResult(
                action="human_review",
                explanation=result.explanation + " (Rebuttal limit reached.)",
                evidence_ids=result.evidence_ids,
                policy_ids=result.policy_ids,
            )

    # 6. Final amount validation
    issues += validate_amounts(result, policy)

    # 7. Build result
    if result.action == "human_review" or issues:
        status = "human_review"
    else:
        status = "completed"

    return WorkflowResult(
        case_id=review.case_id,
        status=status,
        activity_log=log.entries,
        judge_result=result,
        validation_issues=issues,
    )
```

### Helper: human review fallback

```python
def _human_review_result(case_id, log, issues):
    return WorkflowResult(
        case_id=case_id,
        status="human_review",
        activity_log=log.entries,
        judge_result=JudgeResult(
            action="human_review",
            explanation="Review could not complete due to errors or missing model calls.",
        ),
        validation_issues=issues,
    )
```

---

## 7. Validation layer (`checks.py` additions)

### Amount validation

```python
def validate_amounts(result: JudgeResult, policy: dict) -> list[str]:
    """Verify proposed_action.amount_cents matches the ruling type and charge.

    The charge amount is derived from policy["cancellation_fee_after_wait"].
    """
    if result.action != "final_ruling" or result.ruling is None:
        return []

    charge_cents = int(Decimal(str(policy["cancellation_fee_after_wait"])) * 100)
    amount = result.proposed_action.amount_cents
    ruling = result.ruling
    issues = []

    if ruling in ("uphold_charge", "no_action"):
        if amount != 0:
            issues.append(
                f"{ruling} requires zero refund cents; got {amount}."
            )
    elif ruling == "reverse_charge":
        if amount != charge_cents:
            issues.append(
                f"reverse_charge requires {charge_cents} cents (full charge); got {amount}."
            )
    elif ruling == "partial_refund":
        if not (0 < amount < charge_cents):
            issues.append(
                f"partial_refund requires 0 < amount < {charge_cents}; got {amount}."
            )
    return issues
```

### What's already implemented (do not duplicate)

- `validate_references` in `evidence.py` — checks evidence/policy ID existence.
- `no_show_facts` in `checks.py` — wait time, fee eligibility, policy fee.
- `build_review_input` in `evidence.py` — normalizes case + policy into `ReviewInput`.

### What's not yet needed (increment 3+)

- Route-deviation specific validation (planned distance vs. actual route comparison).
- Case-dependent contact-attempt policy checks (the sample policy sets no mandatory contact count, per POLICY-005).

---

## 8. Streamlit UI changes (`app.py`)

### Current state

Read-only: shows case evidence and facts. No agent interaction.

### Increment 1 changes

```python
# Add after the existing evidence display:

st.divider()
st.subheader("Agent review")

if st.button("Run review", type="primary"):
    with st.spinner("Running advocate agents and judge..."):
        result = run_review(case, policy)

# Store result in session state so it persists across reruns
if "review_result" in st.session_state:
    result = st_session_state["review_result"]
    _render_result(result)
```

### Result panel layout

```
┌─────────────────────────────────────────────────┐
│ STATUS: [completed / human_review]              │
│ RULING: [uphold_charge / reverse_charge / ...]  │
│ PROPOSED REFUND: S$X.XX                        │
│ CONFIDENCE: 0.XX                                │
├─────────────────────────────────────────────────┤
│ EXPLANATION                                     │
│ The driver was at the pickup coordinates at     │
│ 08:43 (GPS-005, EVENT-004). The rider's         │
│ location is not independently established...     │
├─────────────────────────────────────────────────┤
│ ACTIVITY LOG                                    │
│ 1. [system] review_prepared                     │
│ 2. [rider_advocate] initial_argument            │
│    • claim: ... (cites: TICKET-001, POLICY-005)│
│ 3. [driver_advocate] initial_argument           │
│    • claim: ... (cites: GPS-005, EVENT-004)     │
│ 4. [judge] first_pass → request_rebuttal        │
│    • question: "Do the records identify..."     │
│ 5. [rider_advocate] rebuttal_response           │
│ 6. [driver_advocate] rebuttal_response           │
│ 7. [judge] second_pass → human_review           │
├─────────────────────────────────────────────────┤
│ VALIDATION ISSUES (if any)                      │
│ • Unknown evidence ID: GPS-999                  │
└─────────────────────────────────────────────────┘
```

### Cited evidence expansion

When the activity log shows a cited ID, render it as an expandable element:

```python
for entry in result.activity_log:
    with st.expander(f"{entry.actor} — {entry.event}"):
        st.json(entry.output)
        # If the output contains evidence_ids, show the source records
        for eid in entry.output.get("evidence_ids", []):
            record = evidence_index.get(eid)
            if record:
                st.caption(f"{eid} ({record.source})")
                st.json(record.data)
```

---

## 9. Testing plan

### New tests (`tests/test_workflow.py`)

| Test | What it checks | Mode |
|---|---|---|
| `test_stub_mode_runs_end_to_end` | `run_review` returns a `WorkflowResult` with a populated activity log using `FAIRRIDE_STUB=1`. | Stub |
| `test_stub_mode_advocates_distinct` | The two advocate entries in the log have different outputs. | Stub |
| `test_stub_mode_judge_action_valid` | The Judge result has a valid action and matching fields per the contract. | Stub |
| `test_citation_rejection_logged` | If a stub advocate cites a fake ID, the issue appears in `validation_issues`. | Stub (modified example) |
| `test_amount_validation_uphold_zero` | A `final_ruling` of `uphold_charge` with non-zero cents produces a validation issue. | Unit (no model) |
| `test_amount_validation_reverse_full` | A `reverse_charge` with less than the charge produces a validation issue. | Unit (no model) |
| `test_amount_validation_partial_range` | A `partial_refund` outside `(0, charge_cents)` produces a validation issue. | Unit (no model) |
| `test_rebuttal_limit_enforced` | If the second Judge call also requests rebuttal, the workflow overrides to `human_review`. | Stub (modified example) |
| `test_model_call_failure_routes_to_human_review` | A `ModelCallError` in any agent call routes to `human_review` with the issue logged. | Stub (mock failure) |

### Existing tests (must not break)

All nine tests in `test_no_show.py` and `test_shared_contract.py` must pass unchanged after the `agents.py` → `agents/` package migration. The `__init__.py` re-exports guarantee backward compatibility for `from agents import ...`.

### Run command

```bash
FAIRRIDE_STUB=1 python3 -m unittest discover -s tests -v
```

For live model tests (manual, requires API key):

```bash
FAIRRIDE_API_KEY=sk-... python3 -c "
from case_data import load_case, load_policy
from workflow import run_review
result = run_review(load_case('DISP-002'), load_policy('sample_no_show'))
print(result.status, result.judge_result.action)
for entry in result.activity_log:
    print(entry.actor, entry.event)
"
```

---

## 10. Activity log format

The activity log is a list of `ActivityEntry` objects:

```python
class ActivityEntry(Contract):
    actor: Literal["system", "rider_advocate", "driver_advocate", "judge"]
    event: str
    output: dict
```

Events used in increment 1:

| Actor | Event | When |
|---|---|---|
| `system` | `review_prepared` | After `build_review_input` |
| `rider_advocate` | `initial_argument` | After first advocate call |
| `driver_advocate` | `initial_argument` | After first advocate call |
| `rider_advocate` | `rebuttal_response` | After rebuttal call (if any) |
| `driver_advocate` | `rebuttal_response` | After rebuttal call (if any) |
| `judge` | `first_pass` | After first Judge call |
| `judge` | `second_pass` | After second Judge call (if rebuttal) |
| `system` | `rebuttal_limit_enforced` | If second Judge call also requests rebuttal |

The `output` field contains the full model response serialized via `model_dump(mode="json")`. This is what the UI renders — it does not render raw model text or hidden reasoning.

---

## 11. Error handling strategy

| Failure | Behavior |
|---|---|
| Missing `FAIRRIDE_API_KEY` and no `FAIRRIDE_STUB` | `run_review` raises `KeyError` with a clear message pointing to `.env.example`. |
| Model returns invalid JSON | `ModelCallError` raised in `call_model`; workflow catches it, logs the issue, routes to `human_review`. |
| Model cites unknown evidence ID | `validate_references` logs the issue; if it's in an advocate output, the Judge still sees it (with the issue noted); if it's in the Judge output, the case routes to `human_review`. |
| Model sets wrong amount for ruling | `validate_amounts` logs the issue; status becomes `human_review`. |
| API rate limit or timeout | `openai` raises `RateLimitError` or `APITimeoutError`; workflow catches these as `ModelCallError`, routes to `human_review`. |
| Second Judge call requests rebuttal again | Workflow overrides to `human_review`, logs the override. |

**Principle:** No failure crashes the app. Every failure routes to `human_review` with a logged issue. The reviewer always sees something.

---

## 12. requirements.txt update

After `agents/client.py` is implemented, add:

```
streamlit
pydantic>=2,<3
openai>=1.0
```

Do not add `openai` until the client code exists (per the project guide rule: "Add model dependencies to requirements.txt only when the corresponding code is implemented").

---

## 13. Open technical decisions

1. **JSON mode vs. structured outputs.** The spec uses `response_format={"type": "json_object"}` (JSON mode) for provider compatibility. If the chosen provider supports `response_format={"type": "json_schema", "json_schema": {...}}` (structured outputs), that's stricter and preferred. Decide after confirming the provider.

2. **Model selection.** `gpt-4o-mini` is the default for cost. The Judge may benefit from a stronger model (`gpt-4o` or equivalent) for reasoning quality. This is an evaluation decision — test both and compare in increment 4.

3. **Token budget.** The `ReviewInput` for DISP-002 is ~3KB of JSON. With two advocate outputs, the Judge's input is ~6-8KB. `max_tokens=2000` for responses should be sufficient. Monitor and adjust.

4. **Retry on parse failure.** Should `call_model` retry once on a parse failure with a "your previous response was invalid JSON" correction? Recommended: no for increment 1 (route to human review); add retry in increment 2 if parse failures are frequent.

---

## 14. Build order within increment 1

| Step | File(s) | Done when |
|---|---|---|
| 1 | `agents/client.py` + `.env.example` | `call_model` returns a parsed `AdvocateResult` from a real API call. |
| 2 | `agents/advocates.py` + `agents/judge.py` + `agents/__init__.py` | `rider_advocate(review)`, `driver_advocate(review)`, `judge(review, r, d)` each return valid results. |
| 3 | `checks.py` | `validate_amounts` passes for all four ruling types. |
| 4 | `workflow.py` | `run_review` returns a `WorkflowResult` with a populated activity log in stub mode. |
| 5 | `app.py` | "Run review" button triggers the workflow and renders the result. |
| 6 | `tests/test_workflow.py` | All new tests pass in stub mode; all existing tests pass unchanged. |
| 7 | Live run | `run_review` on `DISP-002` with a real API key produces a coherent, validated result. |
