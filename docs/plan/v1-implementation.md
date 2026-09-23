# V1 implementation contract

Status: implemented V1 contract; see the application verification record for checks and limits. This supplements, rather than replaces, the architecture decisions.

## Location and runtime

New Python package and UI: `DeepNotes/`. Existing prototype stays untouched. FastAPI, SQLite/FTS5, Pydantic validation, OpenAI-compatible HTTP model adapter, one background thread. No mandatory graph server, embeddings service, or frontend build chain.

Run on loopback with one API process. A database-backed process lease prevents overlapping workers; a lease token fences job commits. Explicitly bounded HTTP calls, retries, and job payloads. Application startup is allowed without credentials; saving/search history remain available, while model-dependent jobs report actionable errors.

## Durable data

- `entries`: original text, optional URL/title, inferred session, context revision.
- `guidance`: append-only explicit context scoped to entry/class/global; not model instructions with execution privileges.
- `jobs`: kind, scope, structure version, entry revision, state, attempts, availability, ownership token, failure code.
- `runs`: validated/intermediate model artifacts, provider model, usage, step outcome.
- `structures` and `classes`: versioned meta catalog with full-text routing index.
- `interpretations`: entry/version/revision representation, broad assignments, explanation, optional clarification, provenance.
- `concepts` and `relations`: evidence-level graph with supporting source IDs and excerpts; relationships are attributed to the current entry's interpretation.
- `entry_search`: version-specific raw plus derived full-text search projection; originals are indexed immediately. Historical projections remain available to pinned queries.
- `interactions`: original question, generated answer, references, source snapshot, planning metadata, success/failure.

No automatic legacy import; schema version 1 is a fresh database. No destructive reset endpoint.

## Version transitions

Every publication creates a fresh immutable catalog version. Copy existing interpretations and graph evidence forward as inherited data, then queue affected entries. Inherited outputs display their originating version and pending-refresh state. New or changed class definitions affect assigned entries; unclassified entries are always reconsidered. Newly created classes conservatively reconsider all entries in V1 because prior classes cannot establish non-membership reliably.

A job can commit only against its captured active version and entry revision. Stale jobs become superseded. Publication schedules replacements, preventing lost work. Rollback creates a NEW version copied from the selected historical version, then schedules reorganization. This avoids stale-job ABA problems and preserves a linear audit trail. Queries pin a version and preserve the source/reference snapshot used to answer.

## Meta catalog and structure proposals

At most 128 active classes in V1, with at most 32 class changes per proposal; expose limits rather than silently dropping data. A class has `id`, `name`, `description`, `aliases`, optional `parent_id`, and `routing_hints`. Stable IDs are validated slugs. Begin with `unclassified`.

Use a compact complete class overview and at most 12 detailed indexed matches. Class/global guidance is included under explicit size budgets. If too much explicit guidance applies, prefer recent records and report context truncation metadata. Notes and retrieved material are always untrusted data.

Structure agent emits upserts and removals, not arbitrary executable code. Validate references, unique names, parent cycles, reserved unclassified class, and support IDs from supplied material. Auto triggers start at 4, 8, 16... eligible saved entries, or 32 entries since the last structural review. Queries/responses do not count. Coalesce pending structure jobs; review snapshots record a high-water mark. Manual/guidance triggers are supported. Corpus input is bounded and mixes recent, unclassified, and older samples; this is a V1 coverage limitation, not exhaustive clustering.

## Guidance and capture feedback

Users can add context to one entry, a class/section, or globally. Entry guidance increments its revision and queues it again. Class/global guidance queues affected entries. All new guidance also requests structural review; sampled entry-only clarifications can inform a class definition without becoming global guidance. The regular organizer receives class-scoped guidance across the catalog under its explicit budget, so a class outside the 12 expanded matches cannot silently lose its meaning. The answer composer also receives guidance for retrieved entries and their pinned assignments. Scope is explicit in the UI, never silently generalized. Organizers return a short interpretation rationale and optional clarification question. Guidance reuse reduces repetition but does not guarantee perfect inference.

## API/UI contracts

All routes below are under `/api`. JSON errors use a `detail` string. List results use `{items: [...]}`. Input length limits are enforced.

- `POST /entries`: `{content, source_url?, source_title?}` -> entry object (includes `id`).
- `GET /entries?limit=30&offset=0`: recent entry objects with `interpretation` (object or null), `status`, `id`, `content`, `created_at`.
- `POST /guidance`: `{scope: 'entry'|'class'|'global', target_id?: string, content}` -> `{id}`. Entry IDs are sent as strings. Global has no target.
- `GET /guidance`: latest explicit guidance records.
- `POST /queries`: `{question}` -> `{id, answer, references: {coverage: 'none'|'partial'|'sufficient', general_knowledge: bool, explanation, notes: [{id, content, source_url, source_title, cited: bool}], live_web: false}, status}`. Answer first; references always below.
- `GET /interactions?q=&limit=20`: persisted interactions, including failure states; history is never default factual evidence.
- `GET /status`: `{jobs: {pending, running, completed, failed, superseded}, active_version, model_configured, demo_mode, worker_running, last_worker_error}`.
- `GET /jobs?limit=30`: job records with sanitized errors.
- `POST /jobs/{id}/retry`: retry failed job; stale scopes enqueue current-version work instead.
- `GET /structure`: `{version, classes, versions}`; versions have `id`, `reason`, `created_at`.
- `POST /structure/reorganize`: queue structural review -> `{job_id}`.
- `POST /structure/rollback`: `{version_id: int}` -> `{version}` (new version ID).

An interpretation includes `summary`, `intent`, `class_ids`, `rationale`, `clarification`, and `inherited` (bool). UI uses text rendering, not untrusted HTML. Show explicit failures rather than fabricating an agent answer during outages.

## Retrieval contract

Agent returns bounded terms and class IDs. Search raw/derived FTS plus class candidates and one-hop concept-linked evidence; no whole-corpus prompt scan. Reserve space for class/graph candidates so full lexical results cannot exclude them entirely. Original-question lookup runs independently of agent terms, so a bad plan cannot displace it. Matching original passages (up to 4,000 characters each, with offsets) are selected rather than blindly taking note prefixes. Postprocessor receives selected source excerpts, query intent, and applicable explicit guidance. Validate cited IDs against supplied evidence. Persist final reference snapshots. Model-generated interactions are searchable separately, never mixed into source evidence by default.

## Operational bounds and implementation tradeoffs

- Each cloud call has a cancellable total deadline (45 seconds by default) and a 2 MB streaming response cap. Three job attempts use exponential backoff starting at 10 seconds; idle polling is 2 seconds.
- Worker recovery coalesces interrupted structural work with pending successors. Publication/rollback preserves outstanding explicit review intent. An expired lease may be recovered by the same owner after laptop sleep only if ownership was not taken over.
- `inherited` means pending refresh; `origin_version` always records the generating version, including when an unaffected result is copied forward without refresh.
- Structure review includes class counts and sampled existing interpretations, plus a compact complete catalog overview and up to 12 full definitions. It does not pass every full class definition on every call.
- Guidance selection uses up to 20 recent applicable records and 12,000 characters, with explicit truncation metadata. Broad scoped guidance remains conditional on its scope.
- SQL/agent records retain detailed input and output context. Disk retention/compaction is deliberately unresolved. Full snapshot copying and conservative reprocessing on new class creation are V1 simplicity choices, not infinite scalability claims.
- Schema version 1 is initialized only for the new app. Legacy import, standalone binary/wheel distribution, note editing/deletion, and retention interfaces are deferred.

## Initial verification

Use temporary SQLite files and a deterministic scripted model for tests: atomic capture; context session boundaries; job retries and recovery; duplicate-safe commits; stale-job fencing; scoped guidance; catalog validation; version publication and rollback; immediate retrieval; source-ID validation; answer-first response contract; persisted failures; API integration and static UI delivery.

Live provider checks are opt-in and require real credentials. An explicit demo adapter can exercise the complete UI/worker without credentials but must be visibly labeled and must never be described as meaningful AI quality validation.
