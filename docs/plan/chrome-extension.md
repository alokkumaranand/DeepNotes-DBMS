# Chrome side-panel addition

Status: implemented and automatically tested as an additive extension; existing application and prototype source files stayed unchanged. Actual Chrome loading and visual checks remain explicit manual verification steps.

## Product scope

A Manifest V3 extension with a full-height Chrome Side Panel, not a popup or an injected page overlay. Chrome owns side-panel placement; users can select right-side placement in Chrome settings. Minimum Chrome 116.

Three compact views: Capture, Ask, and Library. Include page/selection capture, visible attached source, editable notes, answer-first references, recent interpretations, scoped additional context, connection state, and a small setup/settings area. No microphone, history monitoring, automatic page scraping, or background capture.

## Additive integration

- Extension assets live in `DeepNotes/chrome-extension/`.
- New backend launcher: `DeepNotes/deepnotes/extension_api.py`, wrapping the existing app with a narrowly scoped origin adapter. Existing `api.py`, CLI, website, schemas, and environment files are not edited.
- User configures `DEEPNOTES_EXTENSION_ID` (exact 32-character Chrome ID) before starting the extension-aware launcher. The adapter allows only that extension origin and only `/api/` routes. It never allows wildcard extension origins.
- Original same-origin website behavior remains available under the new launcher. Original launcher behavior remains unchanged.
- Extension requests send `X-DeepNotes-Extension` with their runtime ID. This is routing/compatibility identification, not a secret authentication token. Browser-origin checks protect the web boundary; this remains a local single-user application, not a network-authenticated service.
- Host permission and backend selection are limited to `http://127.0.0.1/`; port is configurable (default 8000). No arbitrary remote API URLs or model keys in extension storage.

## Browser responsibilities

- `sidePanel`: native persistent panel alongside tabs.
- `activeTab` and `scripting`: explicit user-initiated main-frame selection/page capture; no all-site read permission.
- `contextMenus`: explicit right-click selection capture, including frame URL when available.
- `storage`: local drafts, backend port, and pending captured selections. No Chrome sync storage.
- Service worker only handles short browser actions/capture queues; long model requests run in the visible panel so MV3 worker lifetime does not cut them off.
- No content scripts, background tab/history tracking, remote scripts, or website-to-extension message bridge.

## Capture semantics

Attaching a page is an explicit action. Source URL/title are shown and stay frozen with the draft as tabs change. Restricted pages fail gracefully; manual notes still work. Selection text is untrusted plain text. Capture does not save a note or contact the model until the user clicks Save/Ask.

Keep drafts per Chrome window across panel close/reopen using local storage. Pending context-menu captures are scoped to their Chrome window. Preserve unsaved text and show a preview before merging/replacing it. Do not silently overwrite a draft's source or truncate a saved note.

## Verification

Passed: 56 Python tests (43 existing + 13 extension adapter), 41 extension JavaScript tests, 10 existing website JavaScript tests, and dependency validation. Covers origin/preflight/header validation, unchanged original-app behavior, manifest permissions/CSP, localhost-only requests, failure handling, drafts/sources, safe rendering, capture restrictions and queues. Full browser loading/visual checks have NOT been completed; see [extension verification](../../DeepNotes/chrome-extension/VERIFICATION.md).

## Additional implementation decisions

- Verify the extension-aware bridge with a harmless status request before every mutation, because some extension contexts omit Origin and the old localhost API can accept originless writes. This prevents accidentally saving through the wrong launcher before reporting a compatibility error.
- Pending captures use a peek/ack protocol: the panel persists the preview before acknowledging removal from the service-worker-managed inbox. This avoids a delivery-to-storage gap on panel close.
- Page selection and source metadata are read together inside the selected document, preventing navigation between separate reads from silently changing source attribution.
- Keep model fetches in the panel, not the short-lived extension service worker. Persisted backend interaction history provides recovery when the panel closes mid-answer; no automatic POST retry.
- Browser APIs and the existing note schema support a single attached source per note. Combining captures with conflicting sources requires an explicit choice; separate notes are recommended when distinct attribution matters.
- Installed-extension setup is intentionally explicit: load unpacked, copy its ID, then configure the additive launcher. No wildcard origin allowance, API key in extension storage, automatic browser-history ingestion, or existing-code rewrite was introduced.

## References

- [Chrome Side Panel API](https://developer.chrome.com/docs/extensions/reference/api/sidePanel?hl=en)
- [Extension cross-origin network requests](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests?hl=en)
- [Chrome activeTab permission](https://developer.chrome.com/docs/extensions/develop/concepts/activeTab?hl=en)
