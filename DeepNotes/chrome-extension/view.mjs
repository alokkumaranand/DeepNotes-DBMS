// Pure state helpers and text-only DOM rendering. No extension globals at import time.
export const NOTE_LIMIT = 20000;
export const POLL_INTERVAL = 10000;
const text = value => typeof value === 'string' ? value : '';

export function safeURL(value) {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
  } catch { return ''; }
}

export function sourceFrom(value) {
  if (!value || typeof value !== 'object') return null;
  const url = safeURL(value.url);
  return url ? { url, title: text(value.title) } : null;
}

export function normalizeCapture(value, windowId) {
  if (!value || typeof value !== 'object' || value.windowId !== windowId || !text(value.id)) return null;
  return { id: value.id, text: text(value.text), url: text(value.url), title: text(value.title), windowId, warning: text(value.warning) };
}

export function emptyDraft() {
  return { content: '', source: null, question: '', pending: null, mode: 'capture', contexts: {}, guidance: { scope: 'entry', target: '', content: '' } };
}

export function normalizeDraft(value, windowId) {
  const clean = emptyDraft();
  if (!value || typeof value !== 'object') return clean;
  clean.content = text(value.content);
  clean.question = text(value.question);
  clean.source = sourceFrom(value.source);
  clean.pending = normalizeCapture(value.pending, windowId);
  if (['capture', 'ask', 'library'].includes(value.mode)) clean.mode = value.mode;
  clean.contexts = Object.fromEntries(Object.entries(value.contexts || {}).filter(([key, value]) => /^\d+$/.test(key) && typeof value === 'string'));
  const guidance = value.guidance || {};
  clean.guidance = { scope: ['entry', 'class', 'global'].includes(guidance.scope) ? guidance.scope : 'entry', target: text(guidance.target), content: text(guidance.content) };
  return clean;
}

export function hasSourceConflict(draft, capture) {
  return Boolean(draft.source && safeURL(capture?.url) !== draft.source.url);
}

export function applyCapture(draft, capture, action) {
  if (!['add', 'replace', 'source'].includes(action)) throw new Error('Choose how to use the capture.');
  const source = sourceFrom(capture);
  if (action === 'source' && !source) throw new Error('This capture has no supported web source.');
  let content = draft.content;
  if (action === 'replace') content = capture.text;
  if (action === 'add' && capture.text) content = content ? `${content}\n\n${capture.text}` : capture.text;
  return { ...draft, content, source: action === 'add' ? (draft.source ? { ...draft.source } : source) : source, pending: null };
}

export function characterCount(value) { return Array.from(value).length; }

export function entryPayload(draft) {
  if (!draft.content.trim()) throw new Error('Write a note or add your captured text first.');
  if (characterCount(draft.content) > NOTE_LIMIT) throw new Error('This note exceeds 20,000 characters. Shorten it before saving; nothing has been truncated.');
  const payload = { content: draft.content };
  if (draft.source) {
    const url = safeURL(draft.source.url);
    if (!url) throw new Error('Remove the unsupported source before saving.');
    if (characterCount(url) > 2000 || characterCount(draft.source.title) > 500) throw new Error('Source metadata is too long. Remove the source before saving this note.');
    payload.source_url = url;
    payload.source_title = draft.source.title;
  }
  return payload;
}

export function sameNote(left, right) {
  return left.content === right.content && (left.source?.url || '') === (right.source?.url || '') && (left.source?.title || '') === (right.source?.title || '');
}

export function postError(error, kind = 'save') {
  const message = error?.message || 'The local backend did not respond.';
  const destination = kind === 'query' ? 'Ask history' : 'Library';
  return `${message} Your draft has been kept. The request may already have committed, especially after a network error or timeout. Check ${destination} before retrying; nothing is retried automatically.`;
}

// Serialize snapshots so a slower old storage write cannot overwrite newer typing.
export function createDraftWriter(write, onError = () => {}) {
  let tail = Promise.resolve();
  return snapshot => {
    const copy = JSON.parse(JSON.stringify(snapshot));
    tail = tail.then(async () => { await write(copy); return true; }).catch(error => { onError(error); return false; });
    return tail;
  };
}

// One preview at a time. A dequeue's own storage event must not drain the inbox.
export function createCaptureInbox({ take, hasPending, accept, onError = () => {} }) {
  let running = false;
  let notified = false;
  return async function request() {
    notified = true;
    if (running || hasPending()) return;
    running = true;
    try {
      for (let attempt = 0; attempt < 2 && !hasPending(); attempt++) {
        notified = false;
        const result = await take();
        if (!result?.ok) throw new Error(result?.error || 'Could not read the capture inbox.');
        if (result.capture) {
          await accept(result.capture);
          if (hasPending() || !notified) break;
        } else if (!notified) break;
      }
    } catch (error) { onError(error); }
    finally { running = false; }
  };
}

export function displayDate(epoch) {
  if (!Number.isFinite(Number(epoch))) return '';
  const date = new Date(Number(epoch) * 1000);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function element(document, tag, className = '', content = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== '') node.textContent = String(content);
  return node;
}

export function sourceLink(document, url, label) {
  const href = safeURL(url);
  if (!href) return null;
  const link = element(document, 'a', 'source-url', label || href);
  link.href = href;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  return link;
}

// Always render the postprocessed answer before its reference snapshot.
export function renderAnswer(document, result) {
  const card = element(document, 'article', 'card answer-card');
  card.append(element(document, 'p', 'eyebrow', 'DEEPNOTES · ANSWER'));
  const answer = element(document, 'div', 'answer-text');
  answer.textContent = text(result.answer) || (result.status === 'failed' ? 'This answer could not be completed.' : 'No answer yet. Refresh history to recover a result that is still processing.');
  card.append(answer);
  if (result.status && result.status !== 'completed') card.append(element(document, 'p', 'helper answer-state', `Status: ${result.status}${result.error ? ` · ${result.error}` : ''}`));
  const section = element(document, 'section', 'references');
  section.setAttribute('aria-label', 'Answer references');
  section.append(element(document, 'h3', '', 'References & perspective'));
  const refs = result.references || {};
  const coverage = ['none', 'partial', 'sufficient'].includes(refs.coverage) ? refs.coverage : 'not available';
  section.append(element(document, 'p', 'reference-meta', `Note coverage: ${coverage} · ${refs.general_knowledge ? 'Includes general knowledge' : 'No general knowledge indicated'} · No live web browsing`));
  if (refs.explanation) section.append(element(document, 'p', 'helper', refs.explanation));
  const notes = Array.isArray(refs.notes) ? refs.notes : [];
  if (!notes.length) section.append(element(document, 'p', 'helper', 'No saved-note references for this response.'));
  for (const note of notes) {
    const item = element(document, 'details', 'reference-item');
    item.append(element(document, 'summary', '', `#${note.id} · ${note.source_title || 'Saved note'} · ${note.cited ? 'Cited' : 'Retrieved, not cited'}${note.excerpted ? ' · Excerpt' : ''}`));
    item.append(element(document, 'p', 'reference-text', note.content || ''));
    const link = sourceLink(document, note.source_url);
    if (link) item.append(link);
    section.append(item);
  }
  card.append(section);
  return card;
}
