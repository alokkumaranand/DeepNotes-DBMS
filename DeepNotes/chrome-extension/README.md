# DeepNotes for Chrome

A calm, full-height **Chrome Side Panel** beside your tabs: Capture, Ask, and Library. No website tab needs to remain open. Your local Python backend still does storage and organization.

**This is an addition.** Existing backend modules, the website, database schema, environment files, and `Prototype_simple/` were not changed. The new `deepnotes/extension_api.py` launcher adds narrowly scoped extension access to the existing app.

## Install once — about 3 minutes

### 1. Load the extension

1. Use Chrome **116 or newer**.
2. Open `chrome://extensions`.
3. Turn on **Developer mode**.
4. Choose **Load unpacked** and select this folder:
   `DeepNotes/chrome-extension/` — the folder containing `manifest.json`, **not** the project root.
5. Copy the extension's **ID** shown on its card (32 lowercase letters). It is also shown in the panel's Settings.
6. Use Chrome's puzzle-piece Extensions menu to **pin DeepNotes**.

Keep this folder in place. Moving or reinstalling an unpacked extension may change its ID; update the backend configuration if that happens.

### 2. Start the extension-aware backend

Stop any running DeepNotes backend first. Open PowerShell in the **`DeepNotes/` application directory**, not inside `chrome-extension/`.

Use your actual ID in this command:

```powershell
$env:DEEPNOTES_EXTENSION_ID = "PASTE_YOUR_32_CHARACTER_EXTENSION_ID_HERE"
.\.venv\Scripts\python.exe -m uvicorn deepnotes.extension_api:create_app --factory --host 127.0.0.1 --port 8000
```

The existing `.venv`, database, and model configuration in `DeepNotes/.env` are reused. If this is a fresh checkout, follow the application README's environment setup first.

The ID variable above lasts for this PowerShell session. For persistence, you may **append** this one line to your existing `DeepNotes/.env` yourself, leaving its other settings intact:

```dotenv
DEEPNOTES_EXTENSION_ID=your_actual_extension_id
```

Do not put the `chrome-extension://` prefix in the variable. Do not copy model API keys into the extension.

**Use the new command instead of `python -m deepnotes` for extension sessions.** The original launcher deliberately retains its same-origin-only browser policy. The new launcher also continues to serve the original website if you want it. Run only one backend process against a database; do not start both launchers together.

### 3. Open it on the right

- Click the pinned **DeepNotes icon**, or use **Alt+Shift+N** if Chrome assigns the suggested shortcut.
- The extension opens in Chrome's native side panel and can remain open while you switch tabs.
- If it appears on the left, open **Chrome Settings → Appearance**, find the side-panel position preference, and select **Right**. Setting names can vary by Chrome version. The extension cannot override this browser preference.
- Drag the panel's divider to choose your width. The interface is designed for a narrow vertical panel, around 320–480 px.

Shortcuts can be changed at `chrome://extensions/shortcuts`.

## Use it

### Capture

- Write a note directly, or select text on a page and choose **Attach current page** in the panel.
- Alternatively, right-click selected text → **Send selection to DeepNotes**. This also works for many embedded-frame selections.
- Inspect the capture preview, then choose **Add to note**, **Replace note & source**, or **Attach source only**.
- Review the attached URL/title and click **Save to library**.

Capture is explicit: opening a panel or switching tabs does **not** scrape or save a page. “Attach current page” captures selected text and page metadata, **not the entire article**. Sources remain fixed with your draft as you change tabs. If you combine text from different pages, the preview explains which source will be retained; use separate notes when you need separate source attribution.

Chrome's temporary `activeTab` permission is granted by actions such as clicking the extension's toolbar icon. After switching to another tab or navigating, click the DeepNotes icon on that tab again before capturing. Restricted pages (`chrome://`, Chrome Web Store restrictions, some PDFs/embedded content) may block selection access. You can still write/paste a note manually.

### Ask

Ask about saved notes. The agent's answer appears first, followed by **References & perspective**: source coverage, general-knowledge use, and related saved notes. The open page and unsaved draft are not automatically included in a question.

Previous answers and failures appear under **Previous conversations**. If the panel closes during a slow response, reopen Ask and refresh history to recover any result saved by the backend. Requests may take up to 270 seconds. No microphone feature is included yet.

### Library and additional context

Open a note to see its original text, interpretation, and any clarification request. Add context directly to that note. In Settings, **Teach DeepNotes your context** lets you choose entry, class/section, or global scope. **Reorganize library** requests a background structural review.

Advanced job retries and version rollback remain available in the existing local website. The extension intentionally keeps the everyday interface smaller.

## Drafts, privacy, and permissions

- Unsaved note/question/context drafts are stored in **Chrome local extension storage**, keyed by Chrome window. They survive closing/reopening the panel in that window. They are not uploaded to Chrome sync.
- Captures stay queued until the panel has persisted their preview and acknowledged receipt. Up to 20 pending captures per window; an overflow is reported rather than silently discarding earlier captures.
- Window IDs are session-local: restoring drafts across a full browser restart or moving between profiles is not guaranteed. Uninstalling the extension removes its local drafts. Saved notes remain in the Python backend database.
- No browsing-history, cookies, all-sites, or always-running content-script permission. No automatic tab activity tracking.
- `activeTab` + `scripting` read selection/page metadata only on explicit capture. `contextMenus` adds the selection command. `sidePanel` opens the panel. `storage` keeps local drafts/settings.
- The only network host permission is **`http://127.0.0.1/`**. Only the port is configurable in Settings; no remote-server URL or API-key field exists.
- Saved notes and queries use your existing backend. In cloud-model mode, selected notes/context may be sent by that backend to its configured provider, just as before.
- The extension ID is public, not a password. Exact browser-origin checks protect against unrelated websites/extensions; this remains a loopback-only single-user service, not an authenticated network server.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Backend unavailable | Start the extension-aware launcher; confirm panel port matches the command. |
| “Regular website backend” / “extension-aware launcher” | Stop `python -m deepnotes` and use the new Uvicorn command above. |
| Extension access not configured / forbidden | Copy the exact ID, set `DEEPNOTES_EXTENSION_ID`, restart the backend. Reloading only the panel cannot change server configuration. |
| Cannot capture the current tab | Click the extension's toolbar icon on that tab again. For iframe text, use the right-click selection command. |
| Selection exceeds the limit | Select less than 20,000 characters. Nothing is silently truncated or saved. |
| Browser requests local-network/site access | Allow access to the local DeepNotes endpoint only if Chrome prompts; browser/enterprise policy may otherwise block it. |
| Saved request timed out | Check Library or Ask history before retrying: the server may already have saved it. Drafts remain; writes are never automatically retried. |
| Another worker owns the database | Stop the other backend. After a forced crash, allow the existing lease to expire (roughly two minutes) before restarting. |
| Changes to extension files are not visible | Click **Reload** on its `chrome://extensions` card, then reopen the panel. |
| Right-click capture shows an exclamation badge | Hover over the toolbar icon for the error; clear pending captures in the panel if its inbox is full. |

### Optional demonstration without a model key

Before the new launcher command, set these in that PowerShell session:

```powershell
$env:DEEPNOTES_DEMO = "true"
$env:DEEPNOTES_DB = "data/extension-demo.sqlite3"
```

The panel labels demo mode. It tests the application flow, not AI quality. After stopping, remove these overrides before normal use:

```powershell
Remove-Item Env:DEEPNOTES_DEMO
Remove-Item Env:DEEPNOTES_DB
```

## Verification and maintenance

From `DeepNotes/`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --test chrome-extension/tests/client.test.mjs chrome-extension/tests/background.test.mjs chrome-extension/tests/panel.test.mjs
node tests/ui.test.cjs
```

Node is only needed for developer tests, not to run the extension. There is no npm build or runtime dependency. Current verification results and browser-check limitations are in [VERIFICATION.md](VERIFICATION.md). Architectural rationale is in [the extension decision note](../../docs/plan/chrome-extension.md).

## Official Chrome references

- [Side Panel API](https://developer.chrome.com/docs/extensions/reference/api/sidePanel?hl=en)
- [activeTab permission](https://developer.chrome.com/docs/extensions/develop/concepts/activeTab?hl=en)
- [Extension network requests](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests?hl=en)
