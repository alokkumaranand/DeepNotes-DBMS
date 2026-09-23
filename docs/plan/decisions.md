# Architectural decision log

Status meanings:
- **Accepted direction:** agreed during discussion; implementation details may remain open.
- **Proposed detail:** recommendation requiring refinement or review.
- **Superseded:** retained for history with a link to its replacement.
- **Implemented engineering default:** a concrete V1 choice recorded for review and future revision, not a claim of explicit user approval for every constant.

## D001 — Local, single-user SQLite deployment

Status: Accepted direction.

Store raw data, processing records, search representations, and graph records in SQLite. Run a background worker while the backend is open. Durable work resumes after restart.

Why: one user, simple operation, transactional consistency, and fewer moving parts than a separate graph service.

Tradeoff: bounded write concurrency and graph-query capabilities. Storage interfaces provide migration boundaries, not a guarantee of effortless migration. Revisit when measured workloads justify another backend or independent workers.

## D002 — Original data and interpretations are separate

Status: Accepted direction.

Preserve original entries and provenance. Derived records reference sources and generation versions. Store intermediate agent outputs and job progress in SQL.

Why: organization will evolve and models can be wrong. Reprocessing must not require recovering original text from generated summaries.

Revisit: exact revision/deletion and retention policies remain open; preserving originals must not imply that future explicit deletion requests are ignored.

## D003 — Two bounded organizers with emerging structure

Status: Accepted direction.

A regular organizer interprets new entries using current broad structure and bounded preceding context. A structure organizer updates broad organization, with automatic and manual triggers. Avoid a fixed subject taxonomy and detailed relationship proliferation.

Why: accommodate arbitrary knowledge, activities, thoughts, questions, and feedback without predicting all future subjects.

Proposed details: early powers-of-two eligible-entry milestones plus a backlog cap; exact thresholds and change limits are undecided. Separate subject, intent, and context rather than forcing everything into one hierarchy.

## D004 — Automatically publish validated, reversible structure versions

Status: Accepted direction.

Publish valid bounded changes automatically, keep previous versions, and support manual reorganization. Retain enough data to reverse interpretation changes without losing source entries.

Why: avoid routine manual supervision while protecting against poor reorganizations.

Tradeoff: publication, assignment backfill, rollback, and in-flight jobs need explicit version semantics. A version column alone does not solve this. Pin retrieval to a published version; finalize transition behavior before building the structure organizer.

## D005 — Durable jobs, not request-scoped background tasks

Status: Accepted direction.

Persist pending/running/completed/failed state and attempt metadata in a jobs table. Use one initial worker thread, retry transient failures, and recover interrupted jobs.

Why: the current prototype can lose work across shutdown and marks extraction failures processed. Separate jobs allow multiple operations and versions per entry.

Tradeoff: the backend must be running. Multi-process execution is not implicitly supported.

## D006 — Indexed derived search plus graph guidance

Status: Accepted direction.

Maintain a preprocessed searchable layer in the same database. Retrieval uses broad organization, indexed representations, bounded graph expansion, and selected originals. Agents emit validated search specifications, not executable SQL or code.

Why: avoid whole-corpus prompt scans while keeping search inspectable and safe. Provide an immediate text index so organization lag does not hide new entries.

Proposed detail: full-text search plus graph assistance first; evaluate embeddings later. Inferred classifications are hints, not hard gates that can permanently hide evidence.

## D007 — Helpful answers beyond saved notes, with provenance

Status: Accepted direction.

Return a curated answer followed by related saved notes. Allow clearly labeled general model knowledge when saved evidence is insufficient. No live web search in V1. Store queries, final responses, retrieved-source references, and generation metadata.

Why: the application should help even before the personal knowledge base is rich.

Guardrail: generated answers and user questions remain distinguishable from user-supplied assertions and are not automatically promoted into verified graph facts.

## D008 — Inferred sessions and optional source metadata

Status: Accepted direction.

Use roughly 30 minutes of inactivity as the initial session boundary and up to three prior session entries as bounded context. Accept optional URL/title fields; defer automatic browser capture.

Why: useful contextual continuity without waiting for an extension.

Tradeoff: time-based sessions are imperfect. Mark inference explicitly and allow unrelated adjacent material to be ignored.

## D009 — Feedback uses the ordinary knowledge model

Status: Accepted direction.

Application feedback is an ordinary entry with an explicit or inferred intent and topic. Retrieve it later to inform development.

Why: exercises the general model and avoids an unnecessary isolated subsystem.

Guardrail: storing feedback does not authorize autonomous software changes. Implementation still follows direct user requests.

## D010 — Configurable cloud models, no initial spending cap

Status: Accepted direction.

User supplies credentials through environment configuration. Cloud model calls are permitted. Provide environment/setup documentation and keep credentials out of stored artifacts and logs.

Why: matches current operation and future packaging needs.

Guardrail: no monetary cap does not mean unbounded loops, unlimited context, or infinite retries. Keep operational bounds and record usage when the provider supplies it.

## D011 — Answer-first presentation

Status: Accepted direction (user clarification).

The postprocessed answer is always first. The references section below explains saved-note coverage, model-knowledge use, and related notes. This refines D007; it does not remove necessary uncertainty or permit fabricated references.

## D012 — Scoped, reusable guidance and interpretation feedback

Status: Accepted direction.

Persist additional user context for an entry, a section/class, or globally. Show how saved notes were interpreted and optionally request clarification without blocking capture. Organizers reuse applicable guidance in later work. Feedback needs no custom subsystem.

## D013 — Shared indexed meta catalog

Status: Accepted direction.

Organization and retrieval use a shared versioned catalog of classes/sections, definitions, aliases, hierarchy, and routing hints. Give agents a compact overview plus relevant detail. Keep this separate from evidence-level concepts and relationships. Agents propose catalog data changes; deterministic code validates and publishes them.

## D014 — Separate application directory

Status: Accepted direction.

All new application code, setup, tests, and runtime data belong under `DeepNotes/`. Do not change `Prototype_simple/` or automatically migrate its data. Planning documents remain under `docs/plan/`.

## Implementation detail tracking

Concrete initial policies and endpoint contracts are recorded in [V1 implementation](v1-implementation.md). These are engineering defaults, not immutable product constraints.

## D015 — Snapshot versions and fenced replacement work

Status: Implemented engineering default; refines D004.

Create a new catalog ID for every publication and rollback. Retain version-specific search projections and copied interpretations. Preserve origin-version metadata; queue affected work and mark pending-refresh copies inherited. Old-version/revision jobs cannot commit. Preserve explicit review requests across version transitions.

Why: simple, testable transitions without mixed-version queries or rollback ABA bugs. Tradeoff: additional disk usage and snapshot-copy cost. New class creation conservatively reprocesses all entries; revisit after real workload measurements.

## D016 — Bounded calls, retries, and candidate pools

Status: Implemented engineering default.

Use cancellable total model-call deadlines, a streaming byte cap, structured outputs, semantic source-ID/excerpt validation, and three durable job attempts. Reserve lexical/class/graph candidate space and always retain an independent original-query search path.

Why: a slow provider or bad plan must not stall the worker indefinitely or make indexed evidence inaccessible. These checks validate contracts and provenance, not factual truth or semantic relevance.

## D017 — Scoped clarification informs structural review

Status: Implemented engineering default; refines D012.

Any new guidance coalesces a structural review request. Entry-only clarification is included when its entry is sampled; it may support a section definition without being generalized as global user guidance. Both organizers see shared catalog context. The composer receives retrieved-entry and assigned-section guidance too.

Why: the user's initial explanation of feedback or a new activity must help establish reusable structure, not remain hidden in a one-off note.

## D018 — Source-based V1 and explicit verification modes

Status: Implemented engineering default.

Ship a separate editable Python application, isolated environment, environment template, tested dependency snapshot, no-build UI, and deterministic demo adapter. Live-provider tests are opt-in and must not be confused with deterministic checks. No automatic legacy import or secret copying.

Why: provides a usable local iteration without prematurely solving distribution. Standalone packaging and asset relocation remain future work.

## Open for future iterations

1. Real-note retrieval/organization evaluation; whether embeddings improve measured misses.
2. Edit/delete semantics, guidance retirement, and artifact/version retention or compaction.
3. Targeted reclassification when adding classes, richer sampling, and reducing snapshot-copy costs.
4. Source import and browser-extension permissions/context capture.
5. Standalone packaging, data-path relocation, authentication if deployment expands beyond loopback.
6. Better context-budget prioritization and user-facing indicators for truncated guidance.

## Change protocol

Append or update decisions when the user approves a meaningful change. Record rationale and consequences. Mark replaced decisions superseded rather than deleting them. Keep proposed details visibly separate from accepted direction; add detailed per-stage plans only when needed.
