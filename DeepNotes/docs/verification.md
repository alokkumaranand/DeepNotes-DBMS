# V1 verification record

## Verified in this implementation pass

Environment: Windows, Python 3.13.6, isolated `.venv`; tested dependencies captured in `requirements.lock`.

| Check | Result |
| --- | --- |
| Python regression/integration suite | **43 tests passed** |
| Dependency-free frontend helper suite | **10 tests passed** (`node tests/ui.test.cjs`) |
| Actual Uvicorn loopback HTTP server | Capture, context, answer, worker completion, shutdown, and restart persistence passed |
| Database integrity | Foreign-key checks, atomic save rollback, duplicate-safe organization, version snapshots, stale-job fencing passed |
| Worker behavior | Retry exhaustion, explicit retry, crash takeover, review coalescing, sleep recovery, and lost-owner fencing passed |
| Context/meta layer | Shared catalog input, entry clarification, section guidance beyond lexical detail matches, structural context use passed |
| Retrieval/provenance | Immediate indexing, independent original-query fallback, graph candidate allocation, long-note passages, valid references, generated-history separation passed |
| Model transport, mocked | Compatible response/usage parsing, total timeout cancellation, early streaming size cap passed |
| Dependency compatibility | `pip check`: no broken requirements |
| Startup interfaces | `python -m deepnotes --help` and opt-in live-smoke help passed |

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/ui.test.cjs
.\.venv\Scripts\python.exe -m pip check
```

The frontend tests use a minimal DOM/fetch stub against the actual inline helpers: safe text rendering, answer-before-references order, HTTP(S) links, timestamps, inherited-version display, JSON action requests, GET deduplication, and errors. They do not simulate browser layout.

The harness sandbox denied some test runs' temporary-directory access; the final complete suites above passed with approved wider execution. No application tests were weakened to accommodate sandbox restrictions.

The installed Starlette version emits a deprecation warning for its `httpx` TestClient adapter. It did not fail the suite; application model transport also uses `httpx`, so switching the test adapter can be evaluated separately later.

## Important defects caught and fixed

- SQLite initialization connection was not explicitly closed; Windows cleanup tests caught the handle leak.
- A running structural job plus a pending successor could violate queue uniqueness during restart recovery.
- UI action requests without bodies lacked the JSON header required by the API's cross-origin protection.
- Retrying a stale failed job could return another still-failed current job without requeuing it.
- Retrieved long notes could omit the only matching passage by always returning their prefix.
- A bad query plan could displace original question terms; full lexical pools could crowd out graph candidates.
- Entry/class clarifications could be absent from the very agents that needed them.
- In-flight explicit structural review intent could be lost during rollback.
- HTTP inactivity timeouts did not bound the whole model response; streamed responses now have both a total deadline and byte cap.

These fixes are covered by deterministic regressions rather than only manual reasoning.

## Not claimed as verified

- **Live cloud-model behavior or answer quality.** The new `.env` contains no API key. No credentials were copied from the prototype and no real-note data was sent to a provider during this pass.
- **Full browser end-to-end behavior or visual review.** Frontend syntax, safe rendering helpers, request construction, and server/static delivery were checked, but the subagent's attempted browser launch was sandbox-denied and did not complete.
- Large-corpus performance, calibrated relevance, complete semantic recall, or factual correctness of generated knowledge.
- Standalone wheel/binary installation, browser extension integration, or legacy-data migration.

## Manual browser smoke checklist

1. Start with a dedicated demo database (`README.md` has commands). Confirm the visible demo warning.
2. Save a note with an optional URL/title. Wait for its interpretation and check status becomes completed.
3. Add entry context, then section/global context where applicable. Confirm scope and saved text remain visible.
4. Ask a question. Confirm the answer appears before references, and related notes identify cited versus merely related sources.
5. Search the interaction history and confirm the saved answer/reference snapshot appears.
6. Click manual reorganize; verify a job is queued/completed. Demo mode makes no class changes.
7. With real or scripted structural changes, inspect versions and confirm rollback requires confirmation and creates a new version.
8. Restart the backend and confirm notes, context, history, and remaining work persist.
9. Check narrow-screen layout, keyboard focus, and error messages in your browser.

## Opt-in live-provider contract smoke test

After configuring your API key, from `DeepNotes/`:

```powershell
.\.venv\Scripts\python.exe scripts/live_smoke.py --confirm-send-sample
```

This makes provider calls using **synthetic sample text only**, in a temporary database. It exercises organization, planning, answer composition, and structural review; it may incur provider charges. It never reads the app's notes database. Without the explicit flag or credentials, it refuses to run. Review the printed answer for quality; a successful schema/contract check is not a semantic-quality guarantee.

## Next useful evaluation

Use a small real collection spanning Java study notes, lecture thoughts, posting drafts, reminders, feedback, and unrelated adjacent entries. For each important question, record expected source notes and whether the answer uses them accurately. Save application feedback as ordinary notes with explicit context. Use those observed misses—not speculative complexity—to choose the next retrieval and organizer improvements.
