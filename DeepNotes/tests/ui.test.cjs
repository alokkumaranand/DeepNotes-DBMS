'use strict';

// No browser, npm packages, live server, or model credentials required.
// Run from DeepNotes/: node tests/ui.test.cjs
// These tests exercise the actual inline helpers, not a copied implementation.
// The small DOM stub checks structure/text safety; it is not a layout/browser test.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const html = readFileSync(join(__dirname, '..', 'static', 'index.html'), 'utf8');
const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)];
assert.equal(scripts.length, 1, 'Expected one self-contained inline application script');
const script = scripts[0][1];
// Stop before event wiring/startup so tests cannot start automatic polling.
const bootstrap = script.indexOf("    $('capture-form').addEventListener");
assert.ok(bootstrap > 0, 'Application bootstrap boundary changed; update test extraction');
const helpers = script.slice(0, bootstrap);

class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.ownText = '';
  }
  set textContent(value) {
    this.ownText = String(value);
    this.children = [];
  }
  get textContent() {
    return this.ownText + this.children.map(child => child.textContent).join('');
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.ownText = ''; this.children = [...children]; }
  set innerHTML(_value) { throw new Error('Unsafe innerHTML assignment'); }
  set outerHTML(_value) { throw new Error('Unsafe outerHTML assignment'); }
  insertAdjacentHTML() { throw new Error('Unsafe HTML insertion'); }
}

function descendants(element) {
  return [element, ...element.children.flatMap(descendants)];
}
function response(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data };
}
function harness(fetchImpl = async () => response({})) {
  const context = vm.createContext({
    document: { createElement: tag => new Element(tag) },
    URL, Date, Map, Set, Number, JSON, Error, TypeError, AbortController,
    setTimeout, clearTimeout, fetch: fetchImpl
  });
  vm.runInContext(helpers + '\nthis.ui = { date, safeUrl, sourceLink, renderAnswer, renderInterpretation, request };', context);
  return context.ui;
}
const malicious = '<img src=x onerror="alert(1)"><script>alert(2)</script>';

test('complete inline JavaScript parses and static DOM references exist', () => {
  assert.doesNotThrow(() => new vm.Script(script));
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
  assert.equal(new Set(ids).size, ids.length, 'Duplicate HTML IDs');
  for (const match of script.matchAll(/\$\('([^']+)'\)/g)) {
    assert.ok(ids.includes(match[1]), 'Missing element: ' + match[1]);
  }
  assert.doesNotMatch(script, /innerHTML|outerHTML|insertAdjacentHTML|document\.write\(/);
  assert.doesNotMatch(html, /<script\b[^>]*\bsrc\s*=/i, 'No external script dependency');
});

test('answer precedes references and all model/source text remains literal text', () => {
  const ui = harness();
  const container = new Element('div');
  ui.renderAnswer(container, {
    answer: malicious,
    status: 'completed',
    references: {
      coverage: 'partial', general_knowledge: true, explanation: malicious, live_web: false,
      notes: [
        { id: 1, content: malicious, source_title: malicious, source_url: 'https://example.com/source', cited: true },
        { id: 2, content: malicious, source_title: malicious, source_url: 'javascript:alert(1)', cited: false }
      ]
    }
  });
  assert.equal(container.children[0].textContent, 'Answer');
  assert.equal(container.children[1].textContent, malicious);
  const references = container.children.at(-1);
  assert.equal(references.tagName, 'SECTION');
  assert.equal(references.className, 'references');
  assert.equal(references.children[0].textContent, 'References & related notes');
  assert.match(references.textContent, /Saved-note coverage: partial/);
  assert.match(references.textContent, /General model knowledge: Used — not independently verified/);
  assert.match(references.textContent, /No live web verification/);
  assert.match(references.textContent, /Note 1 · cited/);
  assert.match(references.textContent, /Note 2 · related, not cited/);
  assert.ok(references.textContent.includes(malicious));
  const nodes = descendants(container);
  assert.equal(nodes.filter(node => ['IMG', 'SCRIPT', 'IFRAME'].includes(node.tagName)).length, 0);
  const links = nodes.filter(node => node.tagName === 'A');
  assert.equal(links.length, 1);
  assert.equal(links[0].href, 'https://example.com/source');
  assert.equal(links[0].textContent, malicious);
});

test('failed/empty answer still has answer-first references and no invented answer', () => {
  const container = new Element('div');
  harness().renderAnswer(container, { status: 'failed', error: malicious });
  assert.equal(container.children[0].textContent, 'Answer');
  assert.equal(container.children[1].textContent, 'No answer was generated.');
  assert.ok(container.textContent.includes(malicious));
  const references = container.children.at(-1);
  assert.equal(references.className, 'references');
  assert.match(references.textContent, /Saved-note coverage: Not reported/);
  assert.match(references.textContent, /General model knowledge: Not reported/);
  assert.match(references.textContent, /No related saved notes returned/);
  assert.match(references.textContent, /No live web verification/);
});

test('only absolute HTTP(S) URLs become safe external links', () => {
  const ui = harness();
  for (const url of [null, '', 42, '/relative', '//example.com', 'javascript:alert(1)', 'data:text/html,x', 'file:///tmp/test', 'ftp://example.com']) {
    assert.equal(ui.safeUrl(url), null, String(url));
    const container = new Element('div');
    ui.sourceLink(container, url, malicious);
    assert.equal(descendants(container).filter(node => node.tagName === 'A').length, 0);
    assert.equal(container.textContent, malicious);
  }
  for (const url of ['http://example.com', 'https://example.com', 'HTTPS://example.com']) {
    const container = new Element('div');
    ui.sourceLink(container, url, malicious);
    const link = container.children[0];
    assert.equal(link.tagName, 'A');
    assert.equal(link.href, new URL(url).href);
    assert.equal(link.target, '_blank');
    assert.equal(link.rel, 'noopener noreferrer');
    assert.equal(link.textContent, malicious);
  }
});

test('Unix-second numeric dates and ISO dates use the same locale formatting', () => {
  const ui = harness();
  const seconds = 1767225600.125;
  assert.equal(ui.date(seconds), new Date(seconds * 1000).toLocaleString());
  assert.equal(ui.date('2026-01-01T00:00:00Z'), new Date('2026-01-01T00:00:00Z').toLocaleString());
  assert.equal(ui.date(null), '');
  assert.equal(ui.date('not a date'), 'not a date');
});

test('interpretation inherited is a boolean and shows originating version', () => {
  const ui = harness();
  const container = new Element('div');
  const interpretation = { summary: malicious, intent: 'remember', class_ids: ['unclassified'], rationale: malicious, clarification: 'More context?', origin_version: 4 };
  ui.renderInterpretation(container, { ...interpretation, inherited: true });
  assert.match(container.textContent, /Inherited interpretation from version 4 — pending refresh/);
  assert.ok(container.textContent.includes(malicious));
  assert.match(container.textContent, /Clarification: More context\?/);
  for (const inherited of [false, 'false', 'true', null, undefined]) {
    ui.renderInterpretation(container, { ...interpretation, inherited });
    assert.doesNotMatch(container.textContent, /Inherited interpretation/);
  }
});

test('all mutations send JSON; parameterless retry/reorganize send empty objects', async () => {
  const calls = [];
  const ui = harness(async (path, options) => { calls.push({ path, ...options }); return response({ id: 1 }); });
  await ui.request('/jobs/1/retry', { method: 'POST' });
  await ui.request('/structure/reorganize', { method: 'POST' });
  await ui.request('/entries', { method: 'POST', body: { content: malicious } });
  await ui.request('/status');
  await ui.request('/test', { method: 'patch' });
  await ui.request('/test', { method: 'DELETE' });
  for (const call of calls.filter(call => call.method !== 'GET')) {
    assert.equal(call.headers['Content-Type'], 'application/json');
    assert.equal(call.headers.Accept, 'application/json');
    assert.equal(call.credentials, 'same-origin');
  }
  for (const index of [0, 1, 4, 5]) assert.equal(calls[index].body, '{}');
  assert.equal(calls[0].path, '/api/jobs/1/retry');
  assert.equal(calls[1].path, '/api/structure/reorganize');
  assert.deepEqual(JSON.parse(calls[2].body), { content: malicious });
  assert.equal(calls[3].body, undefined);
  assert.equal(calls[3].headers['Content-Type'], undefined);
  assert.equal(calls[4].method, 'PATCH');
});

test('concurrent same-path GETs share one fetch and release after completion', async () => {
  let count = 0;
  const resolvers = [];
  const ui = harness(() => { count++; return new Promise(resolve => resolvers.push(resolve)); });
  const first = ui.request('/status');
  const second = ui.request('/status');
  const independent = ui.request('/entries?limit=30&offset=0');
  assert.equal(count, 2, 'Same-path GET deduplicated; independent endpoint still fetched');
  resolvers[0](response({ demo_mode: true }));
  resolvers[1](response({ items: [] }));
  const [a, b] = await Promise.all([first, second, independent]);
  assert.equal(a, b, 'Both callers receive the same response data');
  const next = ui.request('/status');
  assert.equal(count, 3, 'Completed requests are not cached indefinitely');
  resolvers[2](response({ demo_mode: false }));
  assert.equal((await next).demo_mode, false);
});

test('API error detail is preserved and failed GET does not poison retries', async () => {
  let count = 0;
  const ui = harness(async () => {
    count++;
    return count === 1 ? response({ detail: 'Provider unavailable' }, 503) : response({ jobs: {} });
  });
  await assert.rejects(ui.request('/status'), /Provider unavailable/);
  assert.deepEqual(await ui.request('/status'), { jobs: {} });
  assert.equal(count, 2);
});

test('invalid JSON, network failures and aborts produce actionable errors', async () => {
  await assert.rejects(harness(async () => ({ ok: true, json: async () => { throw new SyntaxError('bad JSON'); } })).request('/status'), /invalid JSON/);
  await assert.rejects(harness(async () => { throw new TypeError('fetch failed'); }).request('/status'), /Cannot reach the local API/);
  await assert.rejects(harness(async () => { const error = new Error('aborted'); error.name = 'AbortError'; throw error; }).request('/status'), /timed out.*server may still be working/);
});
