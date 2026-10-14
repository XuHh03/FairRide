# Interface examples

`agent_outputs.json` contains hand-written, case-keyed payloads for integration tests under supplied policy v2.1. These are neither actual model responses nor inputs to any agent. Independent expected labels live in `evaluation.py`.

Eleven cases cover seven automatic decisions and four referrals. DISP-012 illustrates the bounded rebuttal and unresolved historical traffic conflict. Cases requiring mandatory policy referral skip agents entirely.

See `docs/PERSON_B_HANDOFF.md` for the current contracts, original-question context, source IDs and runnable example.
