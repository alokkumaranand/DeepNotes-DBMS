# Roadmap and verification outline

Status: stages 1–5 implemented in the separate `DeepNotes/` application. Deterministic verification is recorded in [the test report](../../DeepNotes/docs/verification.md); real-provider quality and full browser evaluation remain separate follow-up checks. The outline below preserves the original acceptance goals.

## Current prototype: inspected, not runtime-verified

Backend source inspection covered `Prototype_simple/database.py`, `graph_store.py`, `agents.py`, `main.py`, `config.py`, `llm_client.py`, and `requirements.txt`.

Observed issues to address:

- Extraction exceptions mark chunks processed, preventing normal retry.
- Request-scoped background tasks do not provide a durable scheduler or restart recovery.
- Shared in-memory graph mutations and pickle persistence are separate from SQLite completion updates.
- `/graph/rebuild` processes unfinished chunks instead of reconstructing the graph.
- Query seed extraction's exception handler references `seeds` before it is assigned.
- Queries are fed into the organizer without a clear distinction between questions and factual assertions.
- A simple directed graph collapses multiple relation labels between the same node pair.

These observations are not a complete audit. Existing database contents, frontend behavior, installed dependencies, and live model connectivity have not been verified as part of this planning pass.

## Stage 1 — Reliable storage and capture

Implemented: new version-1 schema and app-relative data paths, atomic capture/index/job creation, isolated environment, and setup instructions. The later user decision to keep the prototype separate supersedes automatic migration: legacy data remains untouched and import is deferred.

Checks:
- A saved entry and its job survive restart.
- Partial save failure leaves no orphaned half-operation.
- No prototype data is imported or modified. A future explicit import must preserve source text and identifiers or record a mapping.
- Missing credentials do not prevent saving notes or corrupt state.

## Stage 2 — Worker and regular organizer

Implement one lifecycle-managed worker, recovery, bounded retries, model adapter, output validation, source attribution, and duplicate-safe persistence. Begin with a minimal structure.

Checks:
- Backlog resumes on startup; idle worker does not busy-loop.
- Interrupted work is recovered; duplicate execution does not duplicate evidence.
- Invalid model output remains failed/retryable, never silently successful.
- Unrelated contextual notes do not become assertions attributed to the current entry.
- Shutdown and slow model calls behave predictably.

## Stage 3 — Useful retrieval and interaction history

Implement structured query planning, full-text candidates, bounded graph-assisted expansion, source selection, answer composition, and related-note display. Persist query/answer/source records and distinguish generated content.

Checks:
- Newly saved but not yet organized entries are discoverable.
- Wrong topic assignment does not permanently exclude relevant material.
- An answer's note citations resolve to stored sources.
- Insufficient evidence is stated; general model knowledge is labeled.
- Prior generated answers do not become independent corroboration.
- Provider failures produce a clear failure state rather than a false success.

## Stage 4 — Broad structure evolution

Finalize version transitions before implementation. Add candidate generation/validation, automatic bounded publication, threshold scheduling, manual trigger, targeted backfill, and rollback.

Checks:
- Trigger requests coalesce instead of starting duplicate reorganizations.
- New entries arriving during a run are not lost or incorrectly considered covered.
- Invalid structures do not replace the active version.
- Retrieval remains coherent during backfill.
- Rollback handles both persisted assignments and in-flight jobs.
- Reorganization does not alter originals or invent supporting source records.

## Stage 5 — Usable local application

Complete status/retry/manual-reorganize controls, setup/run documentation, backup instructions, and a manual smoke-test guide. Review local exposure, input validation, and destructive operations.

Checks:
- Follow documented setup in a clean environment.
- Save, query, inspect related notes, restart with unfinished work, retry a failure, and manually reorganize.
- Run deterministic integration tests with a fake model and separately run opt-in live-provider smoke tests.
- Report what was actually tested, including known limits; do not equate mocked success with live model validation.

## Evaluation material

Create a small mixed fixture set: programming highlights with personal explanations, a social-media draft, lecture thoughts, unrelated adjacent entries, reminders, future-study questions, and application feedback. Include ambiguous terms, sparse evidence, and an empty knowledge base.

Measure retrieval usefulness and organization behavior on representative examples. Deterministic tests establish software correctness; qualitative review and repeatable query cases evaluate model usefulness. Neither establishes perfect factual accuracy.

## Future delegation boundaries

Completed delegations: frontend-only implementation against the fixed API contract, and independent read-only backend review. Review findings became regression tests and coordinator-owned fixes. Keep these boundaries for subsequent tasks:

- Tests/fixtures for approved job-state and retrieval contracts.
- Environment/setup documentation and configuration validation.
- UI status and related-note presentation against fixed API payloads.
- Independent review of migrations, recovery, and provenance handling.

Keep cross-cutting schema design, version-transition semantics, and final integration under one coordinator. Each future brief should name owned files, dependencies, inputs/outputs, acceptance tests, and prohibited scope expansion. Avoid parallel edits to shared contracts until their owner has finalized them.
