import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { NOTE_LIMIT, POLL_INTERVAL, safeURL, sourceFrom, normalizeCapture, emptyDraft, normalizeDraft, hasSourceConflict, applyCapture, characterCount, entryPayload, sameNote, postError, createDraftWriter, createCaptureInbox, displayDate, renderAnswer, sourceLink } from '../view.mjs';

const capture = (overrides = {}) => ({ id: 'capture-1', windowId: 17, text: '  selected\n\tcode\n', title: 'Source page', url: 'https://example.com/article', ...overrides });
const source = { url: 'https://old.example/path', title: 'Original source' };

// Minimal text-only DOM double. Deliberately has no HTML parser or innerHTML API.
class Node {
  constructor(tag) { this.tagName = tag; this.children = []; this.attributes = {}; this.className = ''; this._text = ''; }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(node => node.textContent).join(''); }
}
const document = { createElement: tag => new Node(tag) };
const all = root => [root, ...root.children.flatMap(all)];

test('only HTTP(S) sources become clickable', () => {
  for (const url of ['javascript:alert(1)', 'data:text/html,<script>x</script>', 'file:///secret', 'chrome://settings', '//example.com', '', undefined]) assert.equal(safeURL(url), '');
  assert.equal(safeURL('https://example.com/a?q=1#text'), 'https://example.com/a?q=1#text');
  assert.equal(safeURL('http://localhost:8000/'), 'http://localhost:8000/');
  assert.equal(sourceLink(document, 'javascript:alert(1)'), null);
  const link = sourceLink(document, 'https://example.com', '<img src=x onerror=alert(1)>');
  assert.equal(link.target, '_blank');
  assert.equal(link.rel, 'noopener noreferrer');
  assert.equal(link.textContent, '<img src=x onerror=alert(1)>');
});

test('draft normalization preserves whitespace and separates windows', () => {
  const raw = { content: '\n  indented\t\n', source, question: ' question? ', pending: capture(), mode: 'ask', contexts: { 12: ' draft ', bogus: 'not a note' }, guidance: { scope: 'class', target: 'work', content: ' context ' } };
  const first = normalizeDraft(raw, 17);
  const second = normalizeDraft(raw, 18);
  assert.equal(first.content, raw.content);
  assert.equal(first.question, raw.question);
  assert.deepEqual(first.source, source);
  assert.notEqual(first.source, source);
  assert.equal(first.pending.id, 'capture-1');
  assert.equal(second.pending, null);
  assert.deepEqual(first.contexts, { 12: ' draft ' });
  assert.deepEqual(first.guidance, raw.guidance);
  assert.deepEqual(normalizeDraft(null, 17), emptyDraft());
  assert.equal(normalizeDraft({ source: { url: 'javascript:x' }, mode: 'bogus' }, 17).source, null);
  assert.equal(normalizeCapture(capture({ id: '' }), 17), null);
});

test('captured warnings survive draft persistence', () => {
  const normalized = normalizeCapture(capture({ warning: 'Selection access was denied; source only.' }), 17);
  assert.equal(normalized.warning, 'Selection access was denied; source only.');
});

test('preview does not modify a note and sources are frozen copies', () => {
  const existing = { ...emptyDraft(), content: 'Keep me', source };
  const pending = capture();
  const preview = { ...existing, pending };
  assert.equal(preview.content, existing.content);
  assert.deepEqual(preview.source, source);
  const copied = sourceFrom(pending);
  pending.url = 'https://another.example/';
  assert.equal(copied.url, 'https://example.com/article');
});

test('add is explicit, preserves original whitespace and retains conflicting source', () => {
  const draft = { ...emptyDraft(), content: '\told\n', source, pending: capture() };
  assert.equal(hasSourceConflict(draft, draft.pending), true);
  const result = applyCapture(draft, draft.pending, 'add');
  assert.equal(result.content, '\told\n\n\n  selected\n\tcode\n');
  assert.deepEqual(result.source, source);
  assert.notEqual(result.source, source);
  assert.equal(result.pending, null);
  assert.equal(draft.content, '\told\n');
  assert.equal(draft.pending.id, 'capture-1');
});

test('replace explicitly replaces both text and source, source-only preserves editor', () => {
  const original = { ...emptyDraft(), content: 'unsaved', source };
  const incoming = capture();
  const replaced = applyCapture(original, incoming, 'replace');
  assert.equal(replaced.content, incoming.text);
  assert.equal(replaced.source.url, incoming.url);
  const attached = applyCapture(original, incoming, 'source');
  assert.equal(attached.content, 'unsaved');
  assert.equal(attached.source.url, incoming.url);
  assert.throws(() => applyCapture(original, capture({ url: 'chrome://settings' }), 'source'), /supported web source/);
  assert.throws(() => applyCapture(original, incoming, 'automatic'), /Choose/);
});

test('empty note adopts capture source but no helper ever saves it', () => {
  const result = applyCapture(emptyDraft(), capture(), 'add');
  assert.equal(result.content, capture().text);
  assert.equal(result.source.url, capture().url);
  assert.equal(hasSourceConflict(emptyDraft(), capture()), false);
  assert.equal(hasSourceConflict({ source: sourceFrom(capture()) }, capture()), false);
});

test('entry payload preserves source text byte-for-byte, validates without truncation', () => {
  const content = '\n\tconst x = 1;  \n';
  assert.deepEqual(entryPayload({ content, source }), { content, source_url: source.url, source_title: source.title });
  assert.deepEqual(entryPayload({ content, source: null }), { content });
  assert.throws(() => entryPayload({ content: '  \n\t' }), /Write a note/);
  const tooLong = 'a'.repeat(NOTE_LIMIT + 1);
  assert.throws(() => entryPayload({ content: tooLong }), /nothing has been truncated/);
  assert.equal(tooLong.length, NOTE_LIMIT + 1);
  assert.throws(() => entryPayload({ content, source: { url: 'javascript:x', title: '' } }), /unsupported source/);
  assert.throws(() => entryPayload({ content, source: { url: source.url, title: 'a'.repeat(501) } }), /metadata is too long/);
});

test('character limits count Unicode code points like the Python contract', () => {
  assert.equal(characterCount('a😀b'), 3);
  assert.equal(entryPayload({ content: '😀'.repeat(NOTE_LIMIT) }).content.length, NOTE_LIMIT * 2);
});

test('save comparison detects edits to text or frozen metadata', () => {
  const before = { content: 'one', source };
  assert.equal(sameNote(before, { content: 'one', source: { ...source } }), true);
  assert.equal(sameNote(before, { ...before, content: 'two' }), false);
  assert.equal(sameNote(before, { ...before, source: { ...source, title: 'Changed' } }), false);
  assert.equal(sameNote(before, { ...before, source: null }), false);
});

test('failed mutations explain uncertainty and never recommend an automatic retry', () => {
  const save = postError(new Error('Timeout'));
  assert.match(save, /Timeout/);
  assert.match(save, /draft has been kept/);
  assert.match(save, /may already have committed/);
  assert.match(save, /Check Library before retrying/);
  assert.match(save, /nothing is retried automatically/);
  assert.match(postError(new Error('offline'), 'query'), /Check Ask history before retrying/);
});

test('draft writes are serialized snapshots, not mutable live references', async () => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const writes = [];
  let calls = 0;
  const save = createDraftWriter(async value => { calls++; if (calls === 1) await gate; writes.push(value); });
  const draft = { ...emptyDraft(), content: 'first', source: { ...source } };
  const first = save(draft);
  draft.content = 'second'; draft.source.title = 'changed';
  const second = save(draft);
  await Promise.resolve();
  assert.equal(calls, 1);
  release();
  assert.deepEqual(await Promise.all([first, second]), [true, true]);
  assert.equal(writes[0].content, 'first');
  assert.equal(writes[0].source.title, source.title);
  assert.equal(writes[1].content, 'second');
});

test('failed storage is explicitly false (never ACK), later drafts can recover', async () => {
  let calls = 0;
  const errors = [];
  const save = createDraftWriter(async () => { if (++calls === 1) throw new Error('quota'); }, error => errors.push(error.message));
  assert.equal(await save(emptyDraft()), false);
  assert.equal(await save(emptyDraft()), true);
  assert.deepEqual(errors, ['quota']);
});

test('inbox serializes concurrent notifications and stops at one visible preview', async () => {
  let resolveTake;
  let pending = null;
  let calls = 0;
  const take = createCaptureInbox({
    hasPending: () => Boolean(pending),
    take: async () => { calls++; return new Promise(resolve => { resolveTake = resolve; }); },
    accept: async value => { pending = value; },
  });
  const first = take();
  await take(); await take();
  assert.equal(calls, 1);
  resolveTake({ ok: true, capture: capture() });
  await first; await take();
  assert.equal(calls, 1);
  assert.equal(pending.id, 'capture-1');
});

test('inbox captures one at a time and only resumes when preview is consumed', async () => {
  const queue = [capture(), capture({ id: 'capture-2' })];
  let pending = null;
  let calls = 0;
  const take = createCaptureInbox({ hasPending: () => Boolean(pending), take: async () => { calls++; return { ok: true, capture: queue.shift() || null }; }, accept: async value => { pending = value; } });
  await take(); await take();
  assert.equal(calls, 1);
  pending = null;
  await take();
  assert.equal(pending.id, 'capture-2');
  pending = null;
  await take();
  assert.equal(calls, 3);
});

test('an inbox notification during an empty read gets at most one follow-up', async () => {
  let take;
  let calls = 0;
  take = createCaptureInbox({ hasPending: () => false, take: async () => { calls++; void take(); return { ok: true, capture: null }; }, accept: async () => assert.fail('No capture') });
  await take();
  assert.equal(calls, 2);
});

test('inbox failures do not loop or silently fabricate a capture', async () => {
  const errors = [];
  let calls = 0;
  const take = createCaptureInbox({ hasPending: () => false, take: async () => { calls++; return { ok: false, error: 'Storage unavailable' }; }, accept: async () => assert.fail(), onError: error => errors.push(error.message) });
  await take();
  assert.equal(calls, 1);
  assert.deepEqual(errors, ['Storage unavailable']);
});

test('answers are plain text and always precede their reference snapshot', () => {
  const malicious = '<script>alert("not executable")</script>';
  const card = renderAnswer(document, {
    answer: `First paragraph.\n\n${malicious}`, status: 'completed',
    references: { coverage: 'partial', general_knowledge: true, explanation: 'Only part of the question was covered.', live_web: false, notes: [
      { id: 1, content: malicious, source_url: 'javascript:alert(1)', source_title: '<img src=x onerror=alert(1)>', cited: true, excerpted: true },
      { id: 2, content: 'original', source_url: 'https://example.com', cited: false },
    ] },
  });
  const answerIndex = card.children.findIndex(node => node.className === 'answer-text');
  const referencesIndex = card.children.findIndex(node => node.className === 'references');
  assert.ok(answerIndex >= 0 && referencesIndex > answerIndex);
  assert.equal(card.children[answerIndex].textContent, `First paragraph.\n\n${malicious}`);
  assert.match(card.textContent, /Includes general knowledge/);
  assert.match(card.textContent, /No live web browsing/);
  assert.match(card.textContent, /Retrieved, not cited/);
  assert.match(card.textContent, /Excerpt/);
  assert.equal(all(card).filter(node => node.tagName === 'a').length, 1);
  assert.equal(all(card).filter(node => node.tagName === 'script' || node.tagName === 'img').length, 0);
});

test('failed and pending interactions remain recoverable without fabricated answers', () => {
  const failed = renderAnswer(document, { status: 'failed', error: 'Model unavailable', references: null });
  assert.match(failed.textContent, /could not be completed/);
  assert.match(failed.textContent, /Model unavailable/);
  assert.match(failed.textContent, /No saved-note references/);
  const pending = renderAnswer(document, { status: 'pending' });
  assert.match(pending.textContent, /Refresh history/);
});

test('backend epoch seconds are converted to dates', () => {
  assert.ok(displayDate(1710000000).length > 0);
  assert.equal(displayDate('not a date'), '');
});

const html = await readFile(new URL('../sidepanel.html', import.meta.url), 'utf8');
const css = await readFile(new URL('../panel.css', import.meta.url), 'utf8');
const panel = await readFile(new URL('../panel.mjs', import.meta.url), 'utf8');
const view = await readFile(new URL('../view.mjs', import.meta.url), 'utf8');

test('side panel has external module/style assets, no inline JS or remote assets', () => {
  assert.match(html, /<script type="module" src="\.\/panel\.mjs"><\/script>/);
  assert.match(html, /href="\.\/panel\.css"/);
  assert.doesNotMatch(html, /\son\w+\s*=|javascript:|<script(?![^>]*\bsrc=)/i);
  assert.doesNotMatch(html, /<(?:img|script|link)[^>]*(?:src|href)="https?:/i);
  assert.doesNotMatch(css, /@import|url\s*\(/i);
  assert.doesNotMatch(panel + view, /\.innerHTML|\.outerHTML|insertAdjacentHTML|document\.write|\beval\s*\(/);
});

test('static labels and controller selectors resolve to unique elements', () => {
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
  assert.equal(new Set(ids).size, ids.length);
  for (const [, id] of html.matchAll(/\bfor="([^"]+)"/g)) assert.ok(ids.includes(id), `Label target ${id}`);
  for (const [, id] of panel.matchAll(/\$\('([^']+)'\)/g)) assert.ok(ids.includes(id), `Controller target ${id}`);
  for (const mode of ['capture', 'ask', 'library']) assert.ok(ids.includes(`view-${mode}`));
  assert.match(html, /aria-live="polite"/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /prefers-reduced-motion:reduce/);
  assert.match(css, /height:100dvh/);
  assert.match(css, /overflow-y:auto/);
});

test('controller uses direct API calls, window-scoped drafts, persisted preview ACK and visible bounded polling', () => {
  assert.match(panel, /import \{ apiRequest, loadConfig, saveConfig \} from '\.\/client\.mjs'/);
  assert.match(panel, /browser\.windows\.getCurrent\(\)/);
  assert.match(panel, /`draft:\$\{windowId\}`/);
  assert.match(panel, /`inbox:\$\{windowId\}`/);
  assert.match(panel, /type: 'capture-current', windowId/);
  assert.match(panel, /type: 'take-capture', windowId/);
  assert.match(panel, /type: 'ack-capture', windowId, captureId/);
  assert.match(panel, /const stored = await saveDraft\(\);[\s\S]*if \(!stored\) return;[\s\S]*queued && !await acknowledgeCapture/);
  assert.doesNotMatch(panel, /chrome\.tabs|browser\.tabs|setInterval\([^;]*POST|type: ['"](?:query|api|fetch)/);
  assert.equal(POLL_INTERVAL, 10000);
  assert.match(panel, /document\.visibilityState === 'hidden' \|\| refreshing/);
  assert.match(panel, /revision === noteRevision && sameNote/);
  assert.match(panel, /node\.content\.replaceChildren/);
  assert.doesNotMatch(panel, /node\.card\.replaceChildren/);
});
