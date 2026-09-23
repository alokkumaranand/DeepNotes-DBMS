import { apiRequest, loadConfig, saveConfig } from './client.mjs';
import { NOTE_LIMIT, POLL_INTERVAL, emptyDraft, normalizeDraft, normalizeCapture, hasSourceConflict, applyCapture, characterCount, entryPayload, sameNote, postError, createDraftWriter, createCaptureInbox, displayDate, element, sourceLink, renderAnswer } from './view.mjs';

const $ = id => document.getElementById(id);
const browser = globalThis.chrome;
let draft = emptyDraft();
let windowId = null;
let draftKey = null;
let persist = async () => false;
let mode = 'capture';
let saving = false;
let asking = false;
let captureBusy = false;
let refreshing = false;
let loadingOlder = false;
let noteRevision = 0;
let pollTimer;
let noteItems = [];
let historyItems = [];
let classes = [];
let connected = false;
let libraryLoaded = false;
let historyLoaded = false;
let guidanceBusy = false;
let configBusy = false;
let reorganizing = false;
const contextBusy = new Set();
const noteNodes = new Map();
const historyNodes = new Map();
const seenCaptures = new Set();

function notice(message, kind = '') {
  $('notice').textContent = message;
  $('notice').className = `notice ${kind}`;
  $('notice').hidden = !message;
}

function saveDraft() { return persist(draft); }
function updateNoteControls() {
  const count = characterCount(draft.content);
  $('note-count').textContent = `${count.toLocaleString()} / 20,000`;
  $('note-count').classList.toggle('over-limit', count > NOTE_LIMIT);
  $('save-note').disabled = configBusy || saving || !draft.content.trim() || count > NOTE_LIMIT;
  $('ask-submit').disabled = configBusy || asking || !draft.question.trim();
  $('capture-current').disabled = !Number.isInteger(windowId) || captureBusy || Boolean(draft.pending);
}

function syncSource() {
  $('attached-source').hidden = !draft.source;
  if (draft.source) {
    $('source-title').textContent = draft.source.title || 'Attached web page';
    $('source-url').textContent = draft.source.url;
    $('source-url').href = draft.source.url;
  } else {
    $('source-title').textContent = '';
    $('source-url').textContent = '';
    $('source-url').removeAttribute('href');
  }
}

function syncPreview() {
  const capture = draft.pending;
  $('capture-preview').hidden = !capture;
  if (!capture) { updateNoteControls(); return; }
  $('preview-title').textContent = capture.title || 'Captured selection';
  const link = sourceLink(document, capture.url);
  $('preview-url').textContent = link ? capture.url : 'No supported source URL';
  if (link) $('preview-url').href = link.href;
  else $('preview-url').removeAttribute('href');
  $('preview-text').textContent = capture.text || 'Page source only. Write your own note below.';
  const conflict = hasSourceConflict(draft, capture);
  const parts = [];
  if (capture.warning) parts.push(capture.warning);
  if (draft.content) parts.push('Your unsaved note is untouched.');
  if (conflict) parts.push('Different source: Add keeps the current source; Replace switches both note and source. Attach source only changes the source, not your text.');
  else parts.push('Preview only. Choose what to add; Save to library is a separate step.');
  if (characterCount(capture.text) + characterCount(draft.content) > NOTE_LIMIT) parts.push('The combined text may exceed 20,000 characters. Nothing will be truncated.');
  $('preview-warning').textContent = parts.join(' ');
  $('add-capture').textContent = conflict ? 'Add text · keep source' : 'Add to note';
  $('add-capture').disabled = !capture.text && !link;
  $('replace-capture').hidden = !draft.content && !draft.source;
  $('source-only').disabled = !link;
  updateNoteControls();
}

function setMode(next, { focus = false, save = true } = {}) {
  if (!['capture', 'ask', 'library'].includes(next)) return;
  mode = next;
  draft.mode = next;
  for (const button of document.querySelectorAll('[data-mode]')) {
    const active = button.dataset.mode === next;
    button.classList.toggle('is-active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
    $(`view-${button.dataset.mode}`).hidden = !active;
  }
  if (save) void saveDraft();
  if (focus) {
    const heading = $(`${next}-heading`);
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
    $('main-content').scrollTop = 0;
  }
  void refresh();
}

function showSettings(open) {
  $('settings-panel').hidden = !open;
  $('settings-toggle').setAttribute('aria-expanded', String(open));
  $('settings-toggle').setAttribute('aria-label', open ? 'Close settings' : 'Open settings');
  if (open) { $('backend-port').focus(); $('main-content').scrollTop = 0; void loadStructure(); }
  else $('settings-toggle').focus();
}

async function acknowledgeCapture(captureId) {
  try {
    const result = await browser.runtime.sendMessage({ type: 'ack-capture', windowId, captureId });
    if (!result?.ok) throw new Error(result?.error || 'Chrome did not acknowledge the capture.');
    return true;
  } catch (error) {
    notice(`Preview is kept, but the capture inbox could not be acknowledged: ${error.message}. The selection may reappear after reopening.`, 'error');
    return false;
  }
}

async function acceptCapture(value, { queued = false } = {}) {
  const capture = normalizeCapture(value, windowId);
  if (!capture) { notice('A capture from a different window or an invalid capture was ignored.', 'error'); return; }
  if (seenCaptures.has(capture.id)) {
    if (queued && capture.id !== draft.pending?.id) await acknowledgeCapture(capture.id);
    return;
  }
  draft.pending = capture;
  syncPreview();
  const stored = await saveDraft();
  // Peek/ack protocol: never remove a queued capture before its preview is durable.
  if (!stored) return;
  seenCaptures.add(capture.id);
  if (seenCaptures.size > 200) seenCaptures.delete(seenCaptures.values().next().value);
  if (queued && !await acknowledgeCapture(capture.id)) return;
  notice(mode === 'capture' ? 'Capture ready to preview. Your draft has not changed.' : 'A selection is waiting in Capture. Your current draft has not changed.');
}

const takeInbox = createCaptureInbox({
  hasPending: () => Boolean(draft.pending) || captureBusy || !Number.isInteger(windowId),
  take: () => browser.runtime.sendMessage({ type: 'take-capture', windowId }),
  accept: capture => acceptCapture(capture, { queued: true }),
  onError: error => notice(`Could not receive the selection: ${error.message}`, 'error'),
});

async function captureCurrent() {
  if (captureBusy || draft.pending || !Number.isInteger(windowId)) return;
  captureBusy = true;
  updateNoteControls();
  try {
    const result = await browser.runtime.sendMessage({ type: 'capture-current', windowId });
    if (!result?.ok) throw new Error(result?.error || 'Page access is unavailable.');
    await acceptCapture(result.capture);
  } catch (error) {
    notice(`${error.message} After navigating, click the DeepNotes toolbar icon again to grant access, then retry. Restricted Chrome pages cannot be captured; you can always write a manual note.`, 'error');
  } finally { captureBusy = false; updateNoteControls(); void takeInbox(); }
}

async function useCapture(action) {
  if (!draft.pending) return;
  try {
    draft = applyCapture(draft, draft.pending, action);
    noteRevision++;
    $('note-content').value = draft.content;
    syncSource(); syncPreview();
    const stored = await saveDraft();
    if (stored) notice('Added to your draft only. Review it, then save when ready.');
    $('note-content').focus();
    void takeInbox();
  } catch (error) { notice(error.message, 'error'); }
}

async function saveNote(event) {
  event.preventDefault();
  if (saving || configBusy) return;
  let body;
  try { body = entryPayload(draft); } catch (error) { notice(error.message, 'error'); return; }
  const submitted = { content: draft.content, source: draft.source ? { ...draft.source } : null };
  const revision = noteRevision;
  saving = true; updateNoteControls();
  $('save-note').firstElementChild.textContent = 'Saving original…';
  try {
    const result = await apiRequest('/entries', { method: 'POST', body });
    let cleaned = true;
    if (revision === noteRevision && sameNote(draft, submitted)) {
      draft.content = ''; draft.source = null; noteRevision++;
      $('note-content').value = ''; syncSource(); syncPreview();
      cleaned = await saveDraft();
    }
    if (!cleaned) notice(`Note #${result.id} is saved in Library, but the local draft could not be cleared from storage. It may reappear when reopening; check Library before saving it again.`, 'error');
    else notice(`Note #${result.id} saved. ${revision + 1 === noteRevision && !draft.content ? 'DeepNotes will organize it in the background.' : 'Your newer draft edits have been kept.'}`, 'success');
    // A saved entry is already durable even if the following list refresh fails.
    void loadNotes();
  } catch (error) { notice(postError(error), 'error'); }
  finally { saving = false; $('save-note').firstElementChild.textContent = 'Save to library'; updateNoteControls(); }
}

async function ask(event) {
  event.preventDefault();
  if (asking || configBusy || !draft.question.trim()) return;
  const question = draft.question;
  asking = true; updateNoteControls();
  $('ask-progress').hidden = false;
  $('ask-submit').firstElementChild.textContent = 'Thinking…';
  try {
    const result = await apiRequest('/queries', { method: 'POST', body: { question } });
    $('answer-result').replaceChildren(renderAnswer(document, result));
    notice(result.status === 'failed' ? 'This request failed. The result is available in Ask history.' : 'Answer ready. References are below it.', result.status === 'failed' ? 'error' : 'success');
    void loadHistory();
  } catch (error) { notice(postError(error, 'query'), 'error'); }
  finally { asking = false; $('ask-progress').hidden = true; $('ask-submit').firstElementChild.textContent = 'Ask DeepNotes'; updateNoteControls(); }
}

function paintStatus(status) {
  connected = true;
  $('connection-dot').className = `status-dot ${status.demo_mode ? 'demo' : 'online'}`;
  $('connection-label').textContent = status.demo_mode ? 'Demo workspace' : 'Connected locally';
  const jobs = status.jobs || {};
  const messages = [];
  if (status.demo_mode) messages.push('Demo mode · deterministic sample responses, not meaningful AI answers.');
  else if (!status.model_configured) messages.push('Model not configured. You can save notes; AI answers and organization need backend model settings.');
  if (!status.worker_running) messages.push('Organizer is not running. Saved notes remain available.');
  if (status.last_worker_error) messages.push(`Organizer error: ${status.last_worker_error}`);
  if (jobs.failed) messages.push(`${jobs.failed} background job${jobs.failed === 1 ? '' : 's'} failed. See the local app for job details and retry controls.`);
  $('environment-banner').textContent = messages.join(' ');
  $('environment-banner').hidden = !messages.length;
  $('system-detail').textContent = `Structure v${status.active_version ?? '—'} · ${jobs.pending || 0} queued · ${jobs.running || 0} running · ${jobs.failed || 0} failed. Worker ${status.worker_running ? 'running' : 'stopped'}. ${status.last_worker_error || ''}`;
}

function paintOffline(error) {
  connected = false;
  $('connection-dot').className = 'status-dot offline';
  $('connection-label').textContent = 'Backend unavailable';
  $('environment-banner').hidden = false;
  $('environment-banner').textContent = `Cannot reach the local backend: ${error.message || 'connection failed'}. Your window draft is kept locally. Check Settings for the port and extension setup. Previously loaded items may be out of date.`;
}

let notesRequest = null;
async function loadNotes({ older = false } = {}) {
  if (notesRequest) return notesRequest;
  const offset = older ? noteItems.length : 0;
  notesRequest = (async () => {
    try {
      const result = await apiRequest(`/entries?limit=30&offset=${offset}`);
      const items = Array.isArray(result.items) ? result.items : [];
      if (older) {
        const known = new Set(noteItems.map(item => item.id));
        noteItems.push(...items.filter(item => !known.has(item.id)));
      } else {
        const freshIds = new Set(items.map(item => item.id));
        noteItems = [...items, ...noteItems.filter(item => !freshIds.has(item.id))];
      }
      libraryLoaded = true;
      renderNotes();
      $('more-notes').hidden = items.length < 30 && (older || noteItems.length <= 30);
      $('library-helper').textContent = `Showing ${noteItems.length} recent notes. Open a card for the original and scoped context.`;
      updateTargetOptions();
    } catch (error) {
      if (!libraryLoaded) $('notes-list').replaceChildren(element(document, 'p', 'empty-state', `Notes unavailable. ${error.message} Your draft is safe.`));
      else if (mode === 'library') notice(`Could not refresh notes: ${error.message}. Showing previously loaded notes.`, 'error');
    }
  })();
  try { await notesRequest; } finally { notesRequest = null; }
}

function createNoteNode(item) {
  const card = element(document, 'details', 'card note-card');
  const summary = element(document, 'summary');
  const summaryContent = element(document, 'div');
  summary.append(summaryContent);
  const body = element(document, 'div', 'note-body');
  const content = element(document, 'div');
  const form = element(document, 'form', 'context-form');
  const label = element(document, 'label', '', `Add context · only note #${item.id}`);
  const input = element(document, 'textarea');
  input.id = `context-${item.id}`; input.maxLength = 4000; input.rows = 3; input.required = true;
  label.htmlFor = input.id;
  input.placeholder = 'A little more meaning, or an answer to the clarification…';
  input.value = draft.contexts[item.id] || '';
  const button = element(document, 'button', 'secondary-button', 'Save context'); button.type = 'submit';
  const feedback = element(document, 'p', 'context-feedback'); feedback.setAttribute('role', 'status');
  input.addEventListener('input', () => { draft.contexts = { ...draft.contexts, [item.id]: input.value }; void saveDraft(); });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (contextBusy.has(item.id) || configBusy || !input.value.trim()) return;
    contextBusy.add(item.id); button.disabled = true;
    const submitted = input.value;
    try {
      await apiRequest('/guidance', { method: 'POST', body: { scope: 'entry', target_id: String(item.id), content: submitted } });
      if (input.value === submitted) { input.value = ''; delete draft.contexts[item.id]; await saveDraft(); }
      feedback.textContent = 'Context saved for this note only. Reinterpretation is queued.';
    } catch (error) { feedback.textContent = postError(error); }
    finally { contextBusy.delete(item.id); button.disabled = false; }
  });
  form.append(label, input, button, feedback); body.append(content, form); card.append(summary, body);
  return { card, summaryContent, content, signature: '' };
}

function updateNoteNode(node, item) {
  const signature = JSON.stringify(item);
  if (node.signature === signature) return;
  node.signature = signature;
  const meta = element(document, 'div', 'note-meta');
  meta.append(element(document, 'span', '', `#${item.id} · ${displayDate(item.created_at)}`));
  const status = element(document, 'span', 'status-tag', item.status || 'pending');
  if (['failed', 'completed'].includes(item.status)) status.classList.add(item.status);
  meta.append(status);
  const interpretation = item.interpretation;
  node.summaryContent.replaceChildren(meta, element(document, 'p', 'note-summary', interpretation?.summary || item.content), element(document, 'p', 'note-open-hint', 'Original · interpretation · context'));
  const parts = [element(document, 'p', 'eyebrow', 'ORIGINAL NOTE'), element(document, 'p', 'original-content', item.content)];
  const link = sourceLink(document, item.source_url, item.source_title || item.title || item.source_url);
  if (link) parts.push(link);
  if (interpretation) {
    parts.push(element(document, 'p', 'eyebrow', 'HOW DEEPNOTES UNDERSTOOD IT'));
    parts.push(element(document, 'p', 'interpretation-text', interpretation.summary || ''));
    if (interpretation.intent) parts.push(element(document, 'p', 'interpretation-text', `Intent · ${interpretation.intent}`));
    if (interpretation.class_ids?.length) parts.push(element(document, 'p', 'interpretation-text', `Filed in · ${interpretation.class_ids.join(', ')}`));
    if (interpretation.rationale) parts.push(element(document, 'p', 'interpretation-text', interpretation.rationale));
    if (interpretation.origin_version != null) parts.push(element(document, 'p', 'helper', `Interpreted in v${interpretation.origin_version}${interpretation.inherited ? ' · inherited, awaiting refresh' : ''}`));
    if (interpretation.clarification) parts.push(element(document, 'p', 'clarification', `A little clarification? ${interpretation.clarification}`));
  } else parts.push(element(document, 'p', 'helper', item.status === 'failed' ? 'Interpretation failed. Your original is saved; check the backend model settings.' : 'Original saved. Waiting for interpretation.'));
  // Only informational nodes change. The open card and context form are never replaced.
  node.content.replaceChildren(...parts);
}

function renderNotes() {
  $('library-count').textContent = String(noteItems.length);
  if (!noteItems.length) { $('notes-list').replaceChildren(element(document, 'p', 'empty-state', 'Your library starts with one small thought. Save a note in Capture.')); return; }
  const container = $('notes-list');
  for (const child of [...container.children]) if (!child.classList.contains('note-card')) child.remove();
  // Insert new cards around existing cards, without moving focused forms on refresh.
  noteItems.forEach((item, index) => {
    let node = noteNodes.get(item.id);
    if (!node) { node = createNoteNode(item); noteNodes.set(item.id, node); }
    updateNoteNode(node, item);
    if (container.children[index] !== node.card) container.insertBefore(node.card, container.children[index] || null);
  });
}

let historyRequest = null;
async function loadHistory() {
  if (historyRequest) return historyRequest;
  historyRequest = (async () => {
    try {
      const result = await apiRequest('/interactions?limit=20');
      historyItems = Array.isArray(result.items) ? result.items : [];
      historyLoaded = true;
      renderHistory();
    } catch (error) {
      if (!historyLoaded) $('history-list').replaceChildren(element(document, 'p', 'empty-state', `History unavailable. ${error.message}`));
      else if (mode === 'ask') notice(`Could not refresh history: ${error.message}. Showing previously loaded conversations.`, 'error');
    }
  })();
  try { await historyRequest; } finally { historyRequest = null; }
}

function renderHistory() {
  const container = $('history-list');
  if (!historyItems.length) { container.replaceChildren(element(document, 'p', 'empty-state', 'A question is the beginning of a good connection. Your saved answers will appear here.')); return; }
  for (const child of [...container.children]) if (!child.classList.contains('history-card')) child.remove();
  const liveIds = new Set(historyItems.map(item => item.id));
  for (const [id, node] of historyNodes) if (!liveIds.has(id)) { node.card.remove(); historyNodes.delete(id); }
  historyItems.forEach((item, index) => {
    let node = historyNodes.get(item.id);
    if (!node) {
      const card = element(document, 'details', 'card history-card');
      const summary = element(document, 'summary');
      const content = element(document, 'div', 'history-answer');
      card.append(summary, content); node = { card, summary, content, signature: '' }; historyNodes.set(item.id, node);
    }
    const signature = JSON.stringify(item);
    if (node.signature !== signature) {
      const metadata = element(document, 'div', 'note-meta', `#${item.id} · ${displayDate(item.created_at)} · ${item.status || 'pending'}`);
      node.summary.replaceChildren(metadata, element(document, 'p', 'history-question', item.question));
      node.content.replaceChildren(renderAnswer(document, item)); node.signature = signature;
    }
    if (container.children[index] !== node.card) container.insertBefore(node.card, container.children[index] || null);
  });
}

async function refresh() {
  if (document.visibilityState === 'hidden' || refreshing || configBusy) return;
  refreshing = true;
  const currentMode = mode;
  try {
    await Promise.all([
      apiRequest('/status').then(paintStatus).catch(paintOffline),
      currentMode === 'library' ? loadNotes() : currentMode === 'ask' ? loadHistory() : Promise.resolve(),
    ]);
  } finally {
    refreshing = false;
    // A view switch during a request gets one follow-up, not overlapping polling.
    if (mode !== currentMode && document.visibilityState !== 'hidden') void refresh();
  }
}

let structureRequest = null;
async function loadStructure() {
  if (structureRequest) return structureRequest;
  structureRequest = (async () => {
    try {
      const result = await apiRequest('/structure');
      classes = Array.isArray(result.classes) ? result.classes : [];
      $('class-list').replaceChildren(...classes.map(item => element(document, 'span', 'class-chip', `${item.name} · ${item.id}`)));
      updateTargetOptions();
    } catch (error) { $('class-list').replaceChildren(element(document, 'p', 'helper', `Classes unavailable: ${error.message}`)); }
  })();
  try { await structureRequest; } finally { structureRequest = null; }
}

function updateTargetOptions() {
  const scope = $('guidance-scope').value;
  $('guidance-target-field').hidden = scope === 'global';
  $('guidance-target').required = scope !== 'global';
  $('guidance-target-label').textContent = scope === 'class' ? 'Class ID' : 'Note ID';
  $('guidance-target').placeholder = scope === 'class' ? 'For example, unclassified' : 'For example, 12';
  const options = (scope === 'class' ? classes : noteItems).map(item => {
    const option = element(document, 'option'); option.value = String(item.id); option.label = scope === 'class' ? item.name : (item.interpretation?.summary || item.content || '').slice(0, 80); return option;
  });
  $('guidance-targets').replaceChildren(...options);
}

function storeGuidanceDraft() {
  draft.guidance = { scope: $('guidance-scope').value, target: $('guidance-target').value, content: $('guidance-content').value };
  void saveDraft();
}

async function saveGuidance(event) {
  event.preventDefault();
  if (guidanceBusy || configBusy) return;
  const scope = $('guidance-scope').value;
  const content = $('guidance-content').value;
  if (!content.trim()) { notice('Add a little context before saving.', 'error'); return; }
  const body = { scope, content };
  if (scope !== 'global') body.target_id = $('guidance-target').value.trim();
  const submitted = JSON.stringify(draft.guidance);
  guidanceBusy = true; $('guidance-save').disabled = true;
  try {
    await apiRequest('/guidance', { method: 'POST', body });
    if (JSON.stringify(draft.guidance) === submitted) { $('guidance-content').value = ''; storeGuidanceDraft(); }
    notice(`Context saved with ${scope} scope${body.target_id ? ` · ${body.target_id}` : ' · all notes'}. Reorganization is queued.`, 'success');
  } catch (error) { notice(postError(error), 'error'); }
  finally { guidanceBusy = false; $('guidance-save').disabled = false; }
}

function startPolling() {
  clearInterval(pollTimer);
  if (document.visibilityState !== 'hidden') pollTimer = setInterval(() => void refresh(), POLL_INTERVAL);
}

function bindEvents() {
  for (const button of document.querySelectorAll('[data-mode]')) button.addEventListener('click', () => setMode(button.dataset.mode, { focus: true }));
  document.querySelector('.brand').addEventListener('click', event => { event.preventDefault(); setMode('capture', { focus: true }); });
  $('settings-toggle').addEventListener('click', () => showSettings($('settings-panel').hidden));
  $('footer-settings').addEventListener('click', () => showSettings(true));
  $('settings-close').addEventListener('click', () => showSettings(false));
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !$('settings-panel').hidden) showSettings(false); });
  $('note-content').addEventListener('input', () => { draft.content = $('note-content').value; noteRevision++; updateNoteControls(); syncPreview(); void saveDraft(); });
  $('question').addEventListener('input', () => { draft.question = $('question').value; updateNoteControls(); void saveDraft(); });
  $('note-form').addEventListener('submit', saveNote);
  $('ask-form').addEventListener('submit', ask);
  $('capture-current').addEventListener('click', captureCurrent);
  $('add-capture').addEventListener('click', () => void useCapture('add'));
  $('replace-capture').addEventListener('click', () => void useCapture('replace'));
  $('source-only').addEventListener('click', () => void useCapture('source'));
  $('dismiss-capture').addEventListener('click', async () => { draft.pending = null; syncPreview(); await saveDraft(); void takeInbox(); });
  $('remove-source').addEventListener('click', () => { draft.source = null; noteRevision++; syncSource(); syncPreview(); void saveDraft(); notice('Source removed. Your note text is unchanged.'); });
  $('refresh-library').addEventListener('click', () => void loadNotes());
  $('refresh-history').addEventListener('click', () => void loadHistory());
  $('more-notes').addEventListener('click', async () => {
    if (loadingOlder || notesRequest) return;
    loadingOlder = true; $('more-notes').disabled = true;
    try { await loadNotes({ older: true }); } finally { loadingOlder = false; $('more-notes').disabled = false; }
  });
  $('copy-id').addEventListener('click', async () => {
    try { if (!browser?.runtime?.id) throw new Error('Extension ID is available when loaded in Chrome.'); await navigator.clipboard.writeText(browser.runtime.id); notice('Extension ID copied.', 'success'); }
    catch { $('extension-id').focus(); $('extension-id').select(); notice('Select and copy the extension ID with Ctrl+C (⌘C on Mac).'); }
  });
  $('connection-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (configBusy || saving || asking || guidanceBusy || reorganizing || contextBusy.size) { notice('Wait for the current request before changing the backend port.'); return; }
    configBusy = true; updateNoteControls();
    const button = event.currentTarget.querySelector('button'); button.disabled = true;
    try {
      // Let existing GETs settle before switching ports; never mix old backend lists.
      while (refreshing || notesRequest || historyRequest || structureRequest) {
        await Promise.all([notesRequest, historyRequest, structureRequest].filter(Boolean));
        if (refreshing) { notice('A connection check is still running. Try Connect again when it finishes.'); return; }
      }
      const config = await saveConfig({ port: Number($('backend-port').value) });
      if (config?.port) $('backend-port').value = String(config.port);
      noteItems = []; historyItems = []; classes = []; libraryLoaded = false; historyLoaded = false;
      noteNodes.clear(); historyNodes.clear(); $('notes-list').replaceChildren(); $('history-list').replaceChildren(); $('answer-result').replaceChildren();
      notice('Backend port saved. Connecting locally…');
    } catch (error) { notice(`Could not save the port: ${error.message}`, 'error'); }
    finally { configBusy = false; button.disabled = false; updateNoteControls(); void refresh(); void loadStructure(); }
  });
  $('guidance-scope').addEventListener('change', () => { updateTargetOptions(); storeGuidanceDraft(); if ($('guidance-scope').value === 'class') void loadStructure(); });
  $('guidance-target').addEventListener('input', storeGuidanceDraft);
  $('guidance-content').addEventListener('input', storeGuidanceDraft);
  $('guidance-form').addEventListener('submit', saveGuidance);
  $('reorganize').addEventListener('click', async () => {
    if (reorganizing || configBusy) return;
    reorganizing = true; $('reorganize').disabled = true;
    try { const result = await apiRequest('/structure/reorganize', { method: 'POST', body: {} }); notice(`Library review queued · job #${result.job_id}. Original notes are unchanged.`, 'success'); }
    catch (error) { notice(postError(error), 'error'); }
    finally { reorganizing = false; $('reorganize').disabled = false; }
  });
  document.addEventListener('visibilitychange', () => { startPolling(); if (document.visibilityState !== 'hidden') { void refresh(); void takeInbox(); } });
  window.addEventListener('pagehide', () => clearInterval(pollTimer));
  browser?.storage?.onChanged?.addListener((changes, area) => {
    if (area === 'local' && Number.isInteger(windowId) && Object.hasOwn(changes, `inbox:${windowId}`)) void takeInbox();
  });
}

async function boot() {
  $('note-content').disabled = true; $('question').disabled = true; $('capture-current').disabled = true; $('save-note').disabled = true; $('ask-submit').disabled = true;
  try { const config = await loadConfig(); $('backend-port').value = String(config.port); }
  catch (error) { notice(`Could not load settings: ${error.message}`, 'error'); }
  if (browser?.runtime?.id) { $('extension-id').value = browser.runtime.id; $('guide-link').href = browser.runtime.getURL('guide.html'); }
  try {
    if (!browser?.windows?.getCurrent || !browser?.storage?.local) throw new Error('Open this page as a Chrome side panel.');
    const currentWindow = await browser.windows.getCurrent();
    if (!Number.isInteger(currentWindow.id) || currentWindow.id < 0) throw new Error('Chrome did not provide a window ID.');
    windowId = currentWindow.id; draftKey = `draft:${windowId}`;
    const stored = await browser.storage.local.get(draftKey);
    draft = normalizeDraft(stored[draftKey], windowId);
    if (draft.pending) seenCaptures.add(draft.pending.id);
    persist = createDraftWriter(async snapshot => {
      await browser.storage.local.set({ [draftKey]: snapshot });
      $('draft-state').textContent = 'Draft kept locally';
    }, error => {
      $('draft-state').textContent = 'Draft storage unavailable';
      notice(`Could not keep this window draft: ${error.message}. Copy your text before closing the panel.`, 'error');
    });
  } catch (error) {
    notice(`${error.message} Draft persistence is unavailable. Keep this panel open or copy your text before closing it.`, 'error');
    $('draft-state').textContent = 'Temporary draft only';
  }
  $('note-content').value = draft.content; $('question').value = draft.question;
  $('guidance-scope').value = draft.guidance.scope; $('guidance-target').value = draft.guidance.target; $('guidance-content').value = draft.guidance.content;
  $('note-content').disabled = false; $('question').disabled = false;
  bindEvents(); syncSource(); syncPreview(); updateTargetOptions(); updateNoteControls();
  setMode(draft.mode, { save: false });
  // A restored preview is already persisted, including if Chrome closed before ACK.
  if (draft.pending) void acknowledgeCapture(draft.pending.id);
  startPolling(); void takeInbox();
}

void boot();
