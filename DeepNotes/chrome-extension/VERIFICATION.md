# Chrome extension verification

## Automated results

All checks below passed in this implementation pass:

| Suite | Result |
| --- | --- |
| Python backend suite, including extension adapter | **56 passed** (43 existing tests + 13 new adapter tests) |
| Extension JavaScript suites | **41 passed** (18 client/capture/worker tests + 23 panel tests) |
| Existing website JavaScript suite | **10 passed** |
| Dependency validation | `pip check`: no broken requirements |

New tests cover:
- Exact configured extension ID/origin, trusted preflight and private-network headers.
- Wrong/missing/duplicate identities; untrusted origins, paths, hosts, methods and headers.
- Original launcher still rejecting extension writes; original website still working through the new launcher.
- JSON validation and existing API capture/query/context behavior through the adapter.
- Manifest V3 side panel, packaged assets, restricted host permissions, and no inline/remote scripts.
- Localhost-only route/port selection, bridge verification **before** mutations, JSON action bodies, and no automatic write retry.
- Main-frame selection/source consistency, explicit restricted-page fallback, context-menu frame source, and authorized message senders.
- Per-window capture inbox, bounds, preview persistence before acknowledgment, and preservation of unsaved text/source.
- Safe text rendering, answer-before-references ordering, Unicode-aware note validation, draft-write serialization, stable context forms, and visible-only polling guards.

Commands, from `DeepNotes/`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --test chrome-extension/tests/client.test.mjs chrome-extension/tests/background.test.mjs chrome-extension/tests/panel.test.mjs
node tests/ui.test.cjs
.\.venv\Scripts\python.exe -m pip check
```

The harness sandbox denied temporary database access on the first Python attempt; the final combined suite passed with approved wider execution. Earlier subagent Node tests avoided a sandbox child-process pipe restriction via `--test-isolation=none`. Application code/tests were not weakened to accommodate these restrictions.

## Scope of evidence

The Python suite includes the pre-existing real loopback HTTP server/restart test. New adapter tests use FastAPI TestClient, and extension tests use mocked Chrome APIs/fetch/DOM plus real module code. They **do not establish that Chrome's actual side-panel, permission, or rendering behavior has been exercised**.

No real Chrome extension installation, screenshot/visual inspection, browser clipboard, activeTab grant, or full extension-to-backend browser session was completed in this environment. No cloud-model calls were made for this addition. Those are explicit manual smoke checks below—not claimed as passed.

## Manual Chrome smoke checklist

1. Load `chrome-extension/` unpacked in Chrome 116+; confirm no manifest/service-worker errors.
2. Configure its exact ID and start the extension-aware backend. Open Settings in the panel; verify port/ID and connected state.
3. Keep the panel on the right, resize around 320/400/480 px, and check scrolling, keyboard focus and readable labels.
4. On an ordinary HTTP(S) page, select text, click the toolbar icon and Attach current page. Inspect the preview and source before saving.
5. Switch tabs while a draft is present. Confirm its attached source does not change. Re-grant activeTab by clicking the icon on the new tab before another capture.
6. Right-click a selection, including in an iframe where possible. Confirm panel opening, queued preview and correct source URL.
7. Close/reopen the panel before using a preview; verify draft/pending capture survive. Use two Chrome windows to check separation.
8. Save a note; inspect it in Library and add context. Ask about it; verify answer-first references and saved history.
9. Stop the backend: errors should be actionable and drafts should remain. Restart and refresh. Do not automatically repeat a save whose outcome was uncertain.
10. Test a blocked Chrome page: manual entry should still work without claiming successful text capture.
11. Confirm the original website still works with the new launcher and existing notes are unchanged.

## Files deliberately left unchanged

Existing `DeepNotes/deepnotes/` modules (other than adding the new `extension_api.py`), the existing website, original tests, schema, `.env`, package/dependency definitions, and all `Prototype_simple/` code/data were left unchanged. New icon PNGs were generated from the added standard-library-only artwork script. New decisions are recorded separately in `docs/plan/chrome-extension.md`.
