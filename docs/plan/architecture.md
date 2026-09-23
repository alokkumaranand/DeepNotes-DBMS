# Architecture sketch

Status: high-level architecture retained from planning. Concrete implemented defaults and deviations are recorded in [the V1 implementation contract](v1-implementation.md); the executable schema is `DeepNotes/deepnotes/schema.py`.

## 1. Mental model

```text
Capture / UI -> API -> original entries + immediate text index + durable jobs
                                                        |
                                                 background worker
                                                        |
                         active structure -> regular organizer
                                                        |
                                      derived records + graph evidence
                                                        |
                         structure organizer -> candidate structure
                                                        |
                                      validate -> publish -> reprocess

Question -> validated search plan -> indexed retrieval + graph expansion
         -> supporting originals -> curated answer + related notes
         -> persist interaction, sources, and generation metadata
```

Original entries are authoritative records of what was saved, not guarantees that every claim in them is true. The graph and other derived records are rebuildable interpretations.

## 2. One database, separate responsibilities

| Layer | Logical records | Responsibility |
| --- | --- | --- |
| Capture | Entries, source metadata, inferred sessions | Preserve user text, provenance, and capture time |
| Processing | Jobs, runs, artifacts | Track work, intermediate outputs, failures, versions, and retries |
| Search | Chunks, derived entry representations, full-text index | Find candidate evidence efficiently |
| Knowledge | Structure versions, topic/concept nodes, edges, evidence links | Represent evolving organization with source support |
| Interaction | Queries, curated responses, retrieved-source links | Retain what was asked, shown, and used |

Use normal SQL columns for identifiers, statuses, timestamps, relations, and frequently queried attributes. Use schema-versioned JSON for variable agent artifacts, not as a replacement for all relational structure. Exact tables and indexes come later.

Graph nodes have stable IDs, not names as identity. Relations can have multiple types between the same endpoints. Evidence links identify supporting entries/passages and the generating run. Inferred links are explicitly distinguishable from directly supported ones.

### Organization is not one giant tree

Separate these dimensions:

- **Subject:** what the entry concerns.
- **Intent:** explanation, question, reminder, draft, feedback, or another emerging purpose.
- **Context:** session, source, activity, and relevant neighboring entries.

The application schema and small relation vocabulary are controlled by code. Agents evolve topic content and assignments, not SQL schemas or executable behavior. Avoid detailed classifications until there is useful evidence for them.

### Shared meta catalog and user guidance

Maintain an indexed, versioned catalog of classes/sections: stable IDs, names, descriptions, aliases, parent IDs, and routing hints. Both regular organization and query preprocessing receive a compact global overview plus a relevant expanded catalog selection. This is an application-controlled data contract, not an agent-editable SQL schema.

User guidance is persisted with explicit scope: one entry, one class/section, or global. Explicit guidance takes precedence over inferred context but cannot override execution/security rules. The UI shows the current interpretation and an optional clarification question, then accepts additional context. Guidance changes schedule appropriate reprocessing; section/global guidance also requests structural review. Feedback is just one possible use of this general mechanism.

## 3. Context handling

- Start a new inferred session after roughly 30 minutes of inactivity.
- Supply up to three preceding entries from the inferred session, within a context budget.
- Label current entry and contextual entries separately, with their IDs.
- Instruct the organizer to disregard irrelevant neighbors; temporal proximity is not subject identity.
- Record inferred context separately from user-supplied context.
- Context can resolve references, but any resulting relationship must retain its actual supporting sources rather than attributing all evidence to the new entry.
- Accept optional URL/title metadata now; automatic browser collection is deferred.

## 4. Durable background execution

Use one background worker thread in the initial single-process backend. SQLite stores all durable progress; memory only helps wake the worker.

Saving an entry, its initial searchable representation, and its organization job should be atomic. The worker claims a job, records the attempt, performs bounded model calls outside write transactions, validates the result, and commits output plus completion together.

Required behavior:

- Sleep when idle; resume queued work on startup.
- Recover interrupted running jobs through a defined ownership/lease policy.
- Retry transient failures with backoff and a bounded attempt count.
- Retain exhausted failures for inspection and explicit retry; do not mark them successful.
- Make duplicate execution harmless through job/output uniqueness rules.
- Persist run metadata and intermediate artifacts without logging credentials.
- Support graceful shutdown and model-call timeouts.

Configure SQLite for foreign-key enforcement, appropriate concurrency settings, and short transactions. Do not support multiple API processes accidentally sharing an unsafe worker model; define deployment limits explicitly before expanding concurrency.

## 5. Two organizers

### Regular organizer

Input: original entry, bounded neighboring context, and a bounded view of the active structure.

Output: a derived searchable representation, broad assignments, useful concepts/links, and source evidence. Unclear material may remain unclassified. Any confidence metadata is a heuristic, not a calibrated probability.

Use validated structured outputs and deterministic persistence code. Keep this a small pipeline, not an unconstrained autonomous loop. Record structure, prompt/schema, and model versions so affected work can be repeated later.

### Structure organizer

Input: existing structure, aggregated derived material, unclassified entries, and targeted supporting originals. Do not assume the entire growing database fits in one prompt.

Output: a candidate broad structure with proposed additions, merges, splits, and reassignment scope.

- Start with a minimal unclassified structure; avoid inventing a large taxonomy in advance.
- Trigger at early powers-of-two note-count milestones, with an additional maximum backlog threshold and a manual trigger.
- Count eligible user knowledge entries, not generated responses, job rows, or query traffic. Exact eligibility is still to be specified.
- Validate IDs, references, hierarchy constraints, evidence, and change limits before publication.
- Automatically publish valid, bounded changes; retain rejected candidates with reasons.
- Retain prior versions and sufficient assignment/evidence history for rollback.
- Queue only affected entries for reprocessing where practical.

A structure publication and its follow-up jobs must be durable and coordinated. Pin each retrieval to a published version. Before implementation, specify how old assignments remain usable during backfill and how rollback handles in-flight jobs. Never promise consistency by versioning topic names alone.

## 6. Retrieval and answer composition

1. Persist the question as an interaction, not automatically as a factual claim.
2. Give the preprocessing agent the query intent and a bounded, relevant view of the active structure.
3. Validate its search specification: terms, topic IDs, optional intent/context filters, and bounded limits.
4. Application code executes parameterized indexed searches and bounded graph expansion.
5. Rank/deduplicate candidates, then load selected original passages within a context budget.
6. If useful evidence is missing, relax inferred filters and use bounded full-text fallback. Newly saved entries are included through their immediate index.
7. Compose the curated answer and related-note list.
8. Persist the answer, source IDs, evidence used, generation metadata, and any failure state.

Start with SQLite full-text search plus graph-assisted retrieval. Embeddings can be added behind a search interface if evaluation demonstrates a need; initial lexical retrieval has known semantic-recall limits.

### Evidence and generated knowledge

Answers may combine saved material and general model knowledge, but must label the distinction. Do not imply web verification or freshness. Related notes shown below an answer are not necessarily evidence for every statement in it.

Always display the postprocessed answer first, regardless of saved-note coverage. Put coverage (none/partial/sufficient), general-model-knowledge attribution, lack of live web verification, citations, and related notes in a references section below it. Critical uncertainty may still be expressed in the answer itself; do not make unsupported claims appear certain. Use application-validated source IDs when rendering references. Questions and previous answers are searchable as interactions, with provenance labels; generated answers must not recursively reinforce themselves as independent evidence.

Saved material and retrieved text are untrusted data, never instructions to execute or override the pipeline.

## 7. Module boundaries

Proposed responsibilities, not final directory names:

- **API/UI:** validation, capture, queries, status, and manual controls.
- **Application services:** capture transactions, retrieval orchestration, organization, and publication.
- **Domain contracts:** structured inputs/outputs, IDs, state transitions, provenance rules.
- **Storage repositories:** SQL persistence, graph access, full-text search, and migrations.
- **Worker:** claiming, scheduling, retries, recovery, and shutdown.
- **Model adapter:** provider configuration, bounded calls, structured responses, and usage metadata.

Keep business rules out of HTTP handlers and model-provider code. Use narrow interfaces at real change points; avoid a plugin framework or distributed infrastructure prematurely.

## 8. Configuration and existing data

Provide an environment template with placeholders, documented setup, explicit data paths, and ignored secret/runtime files. Keep live credentials out of logs and documentation. Record model usage when available even though no spending limit is currently requested.

Build the new application only under `DeepNotes/`; do not modify or insert files into `Prototype_simple/`. Start with a separate database. Importing legacy data is a later explicit operation requiring backup, schema inspection, and mapping checks. Do not automatically load the legacy pickle graph.
