# Dispute intake and retrieval implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task.

**Goal:** File a complaint against a demo trip and show each advocate retrieving evidence before arguing.

**Architecture:** A read-only local evidence tool serves normalized trip records. Each advocate makes bounded structured source-selection requests through the existing model connection; existing validation and Judge logic remain authoritative.

**Tech stack:** Python, Pydantic, asyncio, existing JSON model client, Streamlit, unittest.

**Spec:** `docs/superpowers/specs/2026-10-15-dispute-intake-retrieval.md`.

## Constraints

Work in the current checkout because this feature builds on the user's uncommitted UI/contract changes. Preserve those changes and the two untracked source documents. No commits, push, provider calls or real platform integration are necessary. Implement inline; request one focused final review of the change.

## Tasks

- [x] Intake and local evidence boundary: tests first for trip catalog, filed complaint validation, immutable fixtures, trip/source isolation. Implement intake helpers in `case_data.py` and a small `retrieval.py` tool/loop; add the source-request contract in `contracts.py`.
- [x] Agent/workflow integration: tests first for planner payload privacy, adaptive requests, complete source coverage, bounded failure, preserved Judge/rebuttal behavior, activity/progress. Add source planners to live/example backends and opt-in `gather_evidence` on both workflow entry points. Preserve default callers.
- [x] UI: tests first for trip/complaint submission, blank input, edited complaint/trip invalidation, explicit scripted/live retrieval labels and evidence-request source links. Add filing controls to the sidebar and retrieval events to Agent activity. Reuse existing report exports.
- [x] Verify: full offline suite, focused review/fixes, documentation/handoff update and restart the local app. Report fresh counts and limitations; leave changes uncommitted.

## Decisions and verification ledger

- Planning: reuse the current checkout and already-authorized work; avoid moving an unfinished integrated change into a new checkout. Retrieval remains opt-in for programmatic callers, so legacy custom backends and evaluation clients keep their contracts.
- Verification: 188 tests ran, 187 passed, one opt-in live batch skipped. Review identified missing planner-failure audit entries; two tests reproduced zero events, the tool boundary now retains available usage and logs failed attempts, and the reviewer verified the fix. No provider calls, commits or pushes.
