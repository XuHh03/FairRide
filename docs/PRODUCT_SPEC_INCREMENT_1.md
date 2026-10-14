> Historical proposal, superseded on14October2026 by `POLICY_V2_1_SPEC.md` and `PERSON_B_HANDOFF.md`. Do not use its old policy, package, stub, model defaults or signatures as current implementation instructions.

# FairRide — Product Spec: Increment 1

**Increment:** No-show end-to-end loop
**Status:** Proposed — 11 October 2026
**Target:** Close the first demoable path — from case load through two advocates, a judge, optional one-round rebuttal, validation, to a visible result on `DISP-002`.

---

## 1. Why this increment

The repo has a solid foundation — Pydantic contracts, evidence IDs, citation checks, no-show facts, and nine passing tests. But `agents.py` and `workflow.py` still raise `NotImplementedError`. There are no model calls, no rulings, and nothing a judge can watch happen. This increment turns the scaffold into a working system for one case.

A working no-show loop is the minimum viable demo. Everything after this — contrasting cases, route deviation, evaluation, submission assets — is improvement, not survival.

---

## 2. Users and their goals

| User | Goal in increment 1 |
|---|---|
| **Dispute reviewer / demo judge** | Select `DISP-002`, run the review, and watch the three agents argue, cite evidence, and reach a validated result. |
| **Rider (recipient)** | Read an explanation that says what happened, which policy applies, and what action is recommended — in plain language. |
| **Driver (recipient)** | Same as rider, from the driver's perspective. The explanation is shared, not asymmetric. |

The system recommends actions. It does not connect to a real payment or refund API.

---

## 3. User stories

### Reviewer

1. **Run a review.** I open the Streamlit app, see `DISP-002` pre-selected, and click "Run review." The system calls the Rider Advocate, the Driver Advocate, and the Judge. I see each step appear in an activity log as it happens.
2. **See cited evidence.** Each claim in the activity log shows the evidence IDs and policy IDs it relies on. I can expand any cited record to read the original source.
3. **See the result.** When the review finishes, I see the Judge's action (final ruling or human review), the ruling if any, the proposed refund amount, the explanation, and the confidence score. If validation failed, I see the issues.
4. **Understand a rebuttal.** If the Judge asked a follow-up question, the activity log shows the question, which advocates responded, and their responses — before the Judge's second pass.

### Rider and Driver (explanation recipients)

5. **Plain-language outcome.** The explanation tells me what the records show, which policy clause decided it, and what happens next. It does not expose raw model reasoning or hidden internals.

---

## 4. Acceptance criteria

Increment 1 is done when all of the following pass on `DISP-002`:

| # | Criterion | How to verify |
|---|---|---|
| AC-1 | **End-to-end run.** `workflow.run_review(case, policy)` returns a `WorkflowResult` without raising, using real model calls for all three agent roles. | Run the workflow with a valid API key; confirm the activity log contains entries from `rider_advocate`, `driver_advocate`, and `judge`. |
| AC-2 | **Distinct advocates.** The Rider Advocate and Driver Advocate return different claims, counterpoints, and unanswered questions, each citing real evidence or policy IDs. | Inspect the activity log; the two advocate entries have different `output` content. |
| AC-3 | **Citation integrity.** Every `evidence_id` and `policy_id` in every advocate and judge output resolves to a real record. Unknown IDs are rejected and logged. | `validate_references` returns an empty list for a clean run; injecting a fake ID produces a logged issue. |
| AC-4 | **Judge action is valid.** The Judge returns exactly one of `request_rebuttal`, `final_ruling`, or `human_review`, with the fields the contract requires for that action. | Pydantic validation passes; the `check_action_fields` validator does not raise. |
| AC-5 | **Rebuttal routing.** If the Judge requests a rebuttal, the workflow passes the question to the named advocate roles, collects their responses, and calls the Judge a second time. This happens at most once. | Run on a case where the Judge requests rebuttal; confirm the activity log shows the question, the responses, and a second judge entry. |
| AC-6 | **Amount validation.** If the Judge issues a `final_ruling`, Python verifies the `amount_cents` matches the ruling type and the charged amount. Mismatches are logged and the case goes to `human_review`. | Inject a `reverse_charge` with `amount_cents=0`; confirm the validation issue is logged and status becomes `human_review`. |
| AC-7 | **Human review fallback.** If the Judge refers to human review, or if any validation fails, `WorkflowResult.status` is `human_review` and the result includes the issues. | Run on a case the Judge refers; confirm status and issues. |
| AC-8 | **Visible result in the UI.** The Streamlit app shows the activity log, the Judge's action and explanation, the proposed refund (if any), confidence, and any validation issues. | Open the app, click "Run review," see all sections render. |
| AC-9 | **No expected answer leaked.** The model never receives the original sample document, the expected ruling, or any label. It receives only `ReviewInput`. | Inspect the model request payload; confirm it contains only `ReviewInput` fields. |
| AC-10 | **Existing tests still pass.** All nine existing unit tests pass unchanged. | `python3 -m unittest discover -s tests -v` exits 0. |

---

## 5. Scope

### In this increment

- Model client: one OpenAI-compatible API connection, env-var key, configurable base URL and model name.
- Rider Advocate: system prompt + model call, returns `AdvocateResult`.
- Driver Advocate: system prompt + model call, returns `AdvocateResult`.
- Judge: system prompt + model call, returns `JudgeResult`.
- Rebuttal: extended advocate signature with optional `question` parameter; workflow routes the Judge's question and calls the Judge again.
- Workflow controller: orchestration, one-round rebuttal limit, activity log, final validation.
- Validation layer: citation existence (already exists), amount checks, policy-condition checks.
- Streamlit UI: "Run review" button, activity log, result panel, validation issues.
- File migration: `agents.py` module → `agents/` package (`client.py`, `advocates.py`, `judge.py`, `__init__.py`).
- `.env.example` and configuration documentation.

### Out of this increment (later increments)

| Item | Increment |
|---|---|
| Contrasting no-show cases (rider-favorable, driver-favorable variants) | Increment 2 |
| Route-deviation category (second dispute type) | Increment 3 |
| Evaluation harness: labelled cases, run logging, metrics | Increment 4 |
| Submission assets: cover image, description, screenshots, GitHub repo | Increment 5 |
| Chat sentiment analysis in advocate prompts | Increment 2 (prompt refinement) |
| Historical behavior profiles as advocate context | Increment 2 (design decision) |
| Advanced agents (fraud detection, evidence collection, precedent) | Stretch — not in scope |

---

## 6. DISP-002: what the system should do with this case

`DISP-002` is deliberately nuanced. The original sample document (in `data/`) says the expected ruling is "UPHELD," but the project's own sample policy creates two material ambiguities:

1. **Designated entrance.** GPS records place the driver at the pickup coordinates (POLICY-005), but no record establishes where the rider stood or which entrance was designated. The rider claims they were at "the lobby," but the records don't confirm this.
2. **Timer conflict.** `EVENT-008` says the fee becomes applicable after the five-minute free wait. The sample policy uses an eight-minute threshold (POLICY-002 vs POLICY-003). This is a preserved contradiction, not a bug to fix.

The `examples/agent_outputs.json` shows the intended flow: the Judge requests a rebuttal about the designated entrance, then refers to human review because the entrance remains unresolved.

**Increment 1 does not require a specific ruling.** The acceptance criteria check that the loop runs, citations are valid, and the result is explainable — not that the Judge reaches a particular outcome. If the model rules `uphold_charge`, `reverse_charge`, or `human_review`, all are acceptable as long as the validation passes and the explanation is coherent. Case-specific expected outcomes are an increment-4 (evaluation) concern.

---

## 7. Demo script (for increment 1)

1. Open the Streamlit app. `DISP-002` is pre-selected with its evidence visible.
2. Click "Run review."
3. Watch the activity log populate:
   - Rider Advocate presents claims citing `TICKET-001`, `POLICY-005`; counterpoints citing `TRIP-001`, `GPS-005`, `POLICY-001`, `POLICY-003`.
   - Driver Advocate presents claims citing `GPS-005`, `EVENT-004`, `CHAT-003`, `EVENT-007`; counterpoints citing `EVENT-008`, `POLICY-002`, `POLICY-003`.
   - Judge receives both arguments. Either requests a rebuttal (entrance ambiguity) or issues a ruling / human review.
4. If rebuttal: the Judge's question appears; the named advocates respond; the Judge reviews a second time.
5. The final result panel shows: action, ruling (if any), proposed refund, explanation, confidence, and any validation issues.

---

## 8. Dependencies and risks

| Dependency / risk | Mitigation |
|---|---|
| **Model API access.** No key is in the repo; the team must confirm which provider they have access to (TokenHub, OpenAI, or another OpenAI-compatible endpoint). | The client reads `FAIRRIDE_API_KEY` and `FAIRRIDE_BASE_URL` from env vars. If no key is available, increment 1 can be developed against the hand-written examples in `examples/agent_outputs.json` as a stub mode. |
| **Structured output reliability.** Models may return JSON that doesn't match the Pydantic schema, or cite IDs that don't exist. | The workflow parses every response with `model_validate_json`, runs `validate_references` after each call, and logs failures. A parse failure routes to human review, not a crash. |
| **Cost and latency.** Three to five model calls per case. | Use a mid-tier model (e.g., `gpt-4o-mini` or equivalent) for advocates; a stronger model for the Judge is an evaluation decision. Log latency per call. |
| **Prompt drift.** The model might invent evidence IDs or use profile data despite instructions. | The validation layer rejects unknown IDs. The system prompt explicitly forbids profile-based reasoning. Profile fields are excluded from `ReviewInput` (already implemented). |

---

## 9. Open product decisions

These should be resolved before or during implementation:

1. **Stub mode for development.** Should the workflow support a `--stub` flag that uses `examples/agent_outputs.json` instead of live model calls? Recommended: yes, for testing the workflow without API costs.
2. **Streaming vs. batch.** Should the UI stream each agent's output as it arrives, or wait for the full result? Recommended: batch for increment 1 (simpler); streaming is an increment-2 UX improvement.
3. **Confidence threshold for human review.** Should low confidence automatically trigger human review, or is it display-only context? Recommended: display-only for increment 1 (matches the current contract); tie it to a threshold in increment 4 (evaluation).

---

## 10. Success definition

Increment 1 succeeds when a reviewer can open the app, run `DISP-002` through the three agents, and see a validated, explained result — even if that result is "this case needs human review because the designated entrance is unresolved." The loop is closed. The demo works.
