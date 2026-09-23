# DeepNotes V1

A local personal memory for notes, thoughts, questions, drafts, and reminders. Original notes stay intact; background organizers build an evolving, searchable interpretation.

**New application only.** `../Prototype_simple/` is not used or modified. Its database is not imported automatically.

## Start here — Windows PowerShell

From this `DeepNotes` directory:

```powershell
# Already created in this workspace; use these commands on a fresh checkout.
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
```

A blank `.env` has been created locally. On a fresh checkout, copy `.env.example` to `.env` **only if `.env` does not already exist**. Set:

```dotenv
LLM_API_KEY=your-key
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=openai/gpt-4o-mini
```

Choose an OpenAI-compatible chat model that supports JSON-object output; a 128K-token context window is recommended. A smaller model may work on small collections but can reject larger structure-review requests. Character-based context budgets do not guarantee an exact token count across languages. Restart after configuration changes.

```powershell
.\.venv\Scripts\python.exe -m deepnotes
```

Open **http://127.0.0.1:8000**. API documentation is at `/docs`. Keep the terminal/backend running for organization; closing the browser does not stop it. Stop with Ctrl+C.

### Try the wiring without API calls

```powershell
# Use a separate database so demo interpretations do not mix with real data.
$env:DEEPNOTES_DB = "data/demo.sqlite3"
.\.venv\Scripts\python.exe -m deepnotes --demo
# After stopping:
Remove-Item Env:DEEPNOTES_DB
```

The UI prominently labels demo mode. It echoes text and exercises the worker/retrieval/UI, **not meaningful AI organization or answer quality**. Demo structural review deliberately makes no changes.

Linux/macOS use `.venv/bin/python` instead of `.venv\Scripts\python.exe`. Python 3.11+ and SQLite with FTS5 are required; automated verification here used Windows/Python 3.13.

## Everyday use

1. **Save a note.** URL/title are optional. It is searchable immediately; interpretation appears after background processing.
2. **Inspect its interpretation.** Check summary, intent, section assignments, rationale, and any clarification question.
3. **Add context.** Choose entry-only, a section/class, or global scope. For example: “This is feedback about DeepNotes, not the Java project.” Entry context remains local; structural review can learn a reusable section definition from it.
4. **Ask a question.** The postprocessed answer is always first. References below explain saved-note coverage, general model knowledge, citations, and related notes. No live web search occurs.
5. **Review organization when useful.** Manual reorganization and historical-structure rollback are in the structure controls.

Guidance is retained and reused. Newer, more specific guidance should resolve conflicts; the original guidance remains auditable. A section does not need to be predefined: start by clarifying an entry, and let structural review propose one.

Questions and answers are saved in searchable interaction history. Generated answers are not silently reused as independent factual evidence.

## What runs in the background

- **Regular organizer:** current note + up to three preceding session notes + shared meta catalog + scoped guidance -> validated interpretation and evidence-linked concepts/relations.
- **Structure organizer:** bounded corpus samples + existing classes + user guidance -> validated broad-section changes. Reviews trigger at early 4/8/16/... note milestones, at 32 notes since the last review, when context is added, or manually.
- **Durable queue:** three attempts with backoff; unfinished work resumes after restart. Failed jobs remain visible and can be retried.

One SQL transaction commits interpretation, graph changes, and job completion. Structure changes create new versions, retain inherited results during refresh, and fence stale work. Rollback creates another version rather than mutating historical IDs.

## Data and operation

- Default data: `data/deepnotes.sqlite3`, relative to this directory regardless of terminal location.
- Keep `.env` private. No existing prototype credentials are copied.
- Notes, explicit context, model artifacts, answers, and reference snapshots are stored **unencrypted** locally. Cloud mode sends selected note/context material to your configured provider.
- Run **one backend process** on loopback. Do not use multiple Uvicorn workers or expose this unauthenticated V1 to a network.
- After a forced process kill, the worker ownership lease may take up to about two minutes to expire. Wait, then restart if startup says another worker owns the database. Do not delete queue rows to work around it.
- After ordinary laptop sleep, the same worker can recover its expired lease if no replacement process has taken ownership.
- Missing credentials do not prevent capture/history. Model jobs will retry, then show a failure. Configure credentials, restart, and retry those jobs.

### Backup / restore

Stop the application cleanly first. Copy the **entire `data/` directory**, including any SQLite `-wal`/`-shm` sidecars, to a private backup location. Restore the complete matching set while the application is stopped; never combine a database file with sidecars from a different backup. Back up `.env` separately only to a secure location. For live backups, use SQLite's backup API rather than copying a running database piecemeal.

## Code map

| File | Responsibility |
| --- | --- |
| `deepnotes/api.py` | HTTP validation, local-origin checks, endpoints, lifecycle |
| `deepnotes/contracts.py` | Bounded API and agent output contracts |
| `deepnotes/schema.py` | Initial SQL schema |
| `deepnotes/storage.py` | Transactions, jobs, versions, graph, indexed retrieval |
| `deepnotes/pipelines.py` | Organizer/query context assembly, validation, composition |
| `deepnotes/models.py` | Cloud adapter, total deadlines, bounded response streaming, demo adapter |
| `deepnotes/worker.py` | Leased worker, retries, wakeup, shutdown |
| `static/index.html` | No-build, answer-first UI with context/status controls |
| `tests/` | Deterministic integration and regression tests |

Architecture and decisions: [plan overview](../docs/plan/README.md), [implementation contract](../docs/plan/v1-implementation.md), [decision log](../docs/plan/decisions.md).

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
# Optional frontend helper checks (Node.js 18+; no npm dependencies):
node tests/ui.test.cjs
```

Tests use isolated temporary databases and fake/scripted providers; transport tests mock HTTP rather than making external requests. See [verification and smoke checks](docs/verification.md) for what was exercised and what still needs real-user evaluation.

## Deliberate V1 limits

- No browser extension, embeddings, live web search, notification scheduling, or user authentication.
- No automatic legacy import, note editing/deletion UI, guidance deletion UI, or artifact-retention/compaction policy yet. Capture preserves originals; corrections use additional context.
- At most 128 active classes and 32 changes per proposal. Structural review samples up to 40 notes, not the whole corpus. Review quality must be evaluated on your actual material.
- Guidance and prompts are bounded; truncation is recorded in run metadata. Matching passages are limited to 4,000 characters per retrieved note. Lexical/graph retrieval can still miss semantic matches.
- Versioned interpretations, indexes, and detailed artifacts favor auditability over disk efficiency. New class creation conservatively reprocesses all entries. Large collections need measured optimization and retention policies.
- Topic/version pinning prevents cross-version mixing, but a query is not a historical snapshot of every concurrent note/guidance change. Its final evidence snapshot is persisted.
- Current installation is editable/source-based. Standalone wheel/binary packaging and asset/data-directory relocation remain future work.
