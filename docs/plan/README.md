# DeepNotes — initial plan

Status: initial V1 implemented separately in `DeepNotes/`; automated verification and limitations are documented with the application. This remains the living architecture record.

## Abstract

DeepNotes is a personal memory for things you learn, think, ask, and plan while using your browser. It keeps your original entries, gradually organizes them in the background, and helps you find and use them later.

The first version will run locally for one user. SQLite will store original entries, processing progress, searchable interpretations, and a knowledge graph. Two organizers will work together: one interprets new entries; the other periodically improves the broad structure. Questions receive a curated answer followed by related saved notes. When saved material is insufficient, the answer may use clearly labeled model knowledge, without live web search.

## What matters most

1. **Never lose the original.** Interpretations can change; your saved words remain available.
2. **Resume unfinished work.** Closing the backend must not erase the processing backlog.
3. **Let organization evolve.** Topics emerge from the material; no fixed subject taxonomy.
4. **Keep evidence clear.** User notes, inferred context, and generated answers are distinguishable.
5. **Stay understandable.** Small modules, explicit contracts, and durable SQL state before additional services.
6. **Be useful before organization finishes.** Saving creates an immediate search index; richer interpretation follows.

## What you will experience

- Save a highlight, thought, question, reminder, draft, or feedback about DeepNotes.
- Get a saved confirmation without waiting for organization.
- Ask a question and receive an answer, with related notes underneath.
- See whether work is pending, completed, or needs retrying.
- Trigger broad reorganization manually when useful.
- Restart the application and continue unfinished work.

The backend must be running for workers to execute. An awake, continuously running service is not part of the initial deployment.

## Read next

- [Architecture](architecture.md): data layers, organizers, retrieval, and module boundaries.
- [Decision log](decisions.md): agreed choices, rationale, and open details.
- [Roadmap](roadmap.md): implementation order and the checks that establish a usable V1.
- [V1 implementation contract](v1-implementation.md): concrete schema/runtime/API policies.
- [Application setup](../../DeepNotes/README.md): how to run and use the new program.
- [Verification](../../DeepNotes/docs/verification.md): evidence, smoke checks, and remaining limitations.

## Scope of this document set

The initial architecture is now backed by a working source implementation and deterministic tests. Detailed current policies live in the implementation contract; open future decisions remain in the decision log. Frontend implementation and an independent backend review were delegated as bounded tasks; shared schema, pipelines, integration, and regression fixes remained with the coordinator.

### Not in V1

- Browser extension, browser-history capture, or automatic page ingestion.
- Live web search or autonomous actions such as posting drafts or scheduling notifications.
- Multiple users, distributed workers, or a dedicated graph database service.
- Executing agent-generated SQL/code or automatically changing application code from feedback.

## Keeping these documents useful

Record important decisions in `decisions.md`, including why and what would justify revisiting them. Update the architecture and roadmap when decisions change. Preserve superseded decisions rather than silently rewriting history. Add detailed implementation plans and delegation briefs only when the corresponding stage is ready.
