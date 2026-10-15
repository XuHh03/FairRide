# Complaint intake and advocate evidence retrieval

## Goal and agreed scope

Accept a short complaint attached to a known demo trip. Rider and Driver Advocates independently request local records before making their arguments. Both have equal access. Preserve existing policy v2.1 decisions, confidence gates, source IDs, rebuttal limits and dashboard.

## Flow

File a dispute → select trip and enter complaint → deterministic policy preflight → parallel advocate retrieval → independent arguments → Judge → optional rebuttal → final validation and recipient explanations.

The sidebar retains sample-case review and adds an explicit filing mode. Demo trips map to existing fixtures and their supported dispute category; this is not an unrestricted production intake classifier. The filed complaint replaces the ticket description in memory, without changing stored records or expected labels. Blank/overlong complaints and unknown trips are rejected. Editing the trip or complaint clears the displayed prior review.

## Retrieval boundary

A read-only local tool exposes only the selected trip's normalized evidence sources. Profiles, answer-bearing sample documents and evaluation labels are unavailable. The planner initially sees the filed ticket, trip ID, role, governing policy and source catalog, not full GPS/chat/fare/traffic contents or derived fact values. It selects sources using structured JSON requests to the existing model client; no framework or native provider tool-call support is required.

Each advocate has at most three retrieval rounds. Tool results return source records and are supplied to subsequent selection calls. All available normalized sources must be reviewed before the argument is accepted, preventing cherry-picking. Already requested sources cannot silently consume an unlimited budget. The final argument receives the full retrieved evidence package and canonical facts; the Judge receives the complete package. Rebuttals reuse gathered records. Policy-mandated preflight referrals still avoid agent calls.

Every request logs the role, trip, sources, returned IDs, brief purpose, usage and duration. Schema errors, cross-trip requests and exhausted retrieval budgets fail operationally before a Judge ruling. There is no arbitrary filesystem/network query tool and no new paid verification call.

## Compatibility and limits

Retrieval is enabled explicitly for filed disputes; existing sample/evaluation callers keep the current prepared-package flow. The live backend selects sources with the model. Example mode uses scripted selections and is labelled accordingly. This MVP reads local simulated sources, not real Ryde services; it does not authenticate trip ownership, persist new disputes or execute payments.

## Verification

Tests must cover complaint validation and immutable fixtures, trip isolation, excluded profiles/labels, actual source requests and returned records, adaptive rounds, equal access, retrieval limits/failures, original rebuttal behavior and observable logs/progress. UI tests file both supported categories, invalidate stale results on edits, and inspect request sources. Standard tests use no provider calls.
