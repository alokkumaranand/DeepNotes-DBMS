import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {apiRequest, loadConfig, saveConfig, validatePort, requestURL, ApiError} from '../client.mjs';
import {normalizeCapture, appendInbox} from '../capture.mjs';
import {readFileSync, existsSync} from 'node:fs';

const id = 'a'.repeat(32);
let stored;
beforeEach(() => {
  stored = {};
  globalThis.chrome = {runtime: {id}, storage: {local: {
    get: async key => ({[key]: stored[key]}),
    set: async values => Object.assign(stored, values),
  }}};
});
const reply = (data, {status = 200, bridge = true} = {}) => ({ok: status >= 200 && status < 300, status,
  headers: {get: key => bridge && key.toLowerCase() === 'x-deepnotes-extension-bridge' ? '1' : null},
  json: async () => data});

test('manifest is a minimally privileged MV3 native side panel', () => {
  const manifest = JSON.parse(readFileSync(new URL('../manifest.json', import.meta.url)));
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.minimum_chrome_version, '116');
  assert.deepEqual(manifest.host_permissions, ['http://127.0.0.1/*']);
  assert.ok(manifest.permissions.includes('sidePanel'));
  for (const permission of ['tabs', 'history', '<all_urls>', 'webRequest', 'cookies', 'debugger']) assert.ok(!manifest.permissions.includes(permission));
  assert.equal(manifest.content_scripts, undefined);
  assert.equal(manifest.externally_connectable, undefined);
  assert.equal(manifest.action.default_popup, undefined);
  assert.ok(!manifest.content_security_policy.extension_pages.includes('unsafe-inline'));
  assert.ok(!manifest.content_security_policy.extension_pages.includes('unsafe-eval'));
  for (const file of [manifest.side_panel.default_path, manifest.background.service_worker, ...Object.values(manifest.icons)]) {
    assert.ok(existsSync(new URL('../' + file, import.meta.url)), `Missing packaged file ${file}`);
  }
});

test('port settings cannot become arbitrary external URLs', async () => {
  assert.deepEqual(await loadConfig(), {port: 8000});
  assert.deepEqual(await saveConfig({port: '8123'}), {port: 8123});
  assert.deepEqual(await loadConfig(), {port: 8123});
  for (const port of [0, -1, 65536, 'https://evil.example', '8000/path', NaN, 1.5, '']) assert.throws(() => validatePort(port));
  assert.equal(requestURL('/status', 'GET', 80), 'http://127.0.0.1/api/status');
});

test('only known localhost API operations are accepted', () => {
  assert.equal(requestURL('/entries?limit=20', 'GET', 8000), 'http://127.0.0.1:8000/api/entries?limit=20');
  for (const path of ['https://evil.example', '//evil.example', '/../../reset', '/status#fragment', '/foo', '/entries\\escape']) assert.throws(() => requestURL(path, 'GET', 8000));
  assert.throws(() => requestURL('/entries', 'DELETE', 8000));
  assert.throws(() => requestURL('/queries?override=true', 'POST', 8000));
  assert.match(requestURL('/jobs/2/retry', 'POST', 8000), /jobs\/2\/retry$/);
});

test('mutations verify bridge before sending JSON, with no cookies or redirects', async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => { calls.push({url, options}); return reply({id: 1}); };
  assert.deepEqual(await apiRequest('/entries', {method: 'POST', body: {content: '  Code\n'}}), {id: 1});
  assert.equal(calls.length, 2);
  assert.match(calls[0].url, /api\/status$/);
  const {options} = calls[1];
  assert.equal(options.headers['X-DeepNotes-Extension'], id);
  assert.equal(options.headers['Content-Type'], 'application/json');
  assert.equal(options.body, JSON.stringify({content: '  Code\n'}));
  assert.equal(options.credentials, 'omit');
  assert.equal(options.redirect, 'error');
});

test('old launcher is detected BEFORE non-idempotent writes', async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; return reply({}, {bridge: false}); };
  await assert.rejects(apiRequest('/entries', {method: 'POST', body: {content: 'must not send'}}), /extension-aware launcher/);
  assert.equal(calls, 1);
});

test('action posts use empty JSON and GETs remain bodyless', async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => { calls.push(options); return reply({}); };
  await apiRequest('/structure/reorganize', {method: 'POST'});
  assert.equal(calls[1].body, '{}');
  await apiRequest('/status');
  assert.equal(calls[2].body, undefined);
  assert.equal(calls[2].headers['Content-Type'], undefined);
});

test('backend rejection is actionable without automated mutation retry', async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; return reply({detail: 'Configure extension ID'}, {status: 403, bridge: false}); };
  await assert.rejects(apiRequest('/entries', {method: 'POST'}), error => error instanceof ApiError && error.status === 403 && !error.uncertain);
  assert.equal(calls, 1);
});

test('lost mutation responses preserve uncertainty, never silently retry', async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; if (calls === 1) return reply({}); throw new TypeError('Failed to fetch'); };
  await assert.rejects(apiRequest('/entries', {method: 'POST'}), error => error.uncertain && /may already have been saved/.test(error.message));
  assert.equal(calls, 2);
});

test('GET timeout and malformed successful responses are explicit failures', async () => {
  globalThis.fetch = async () => { const error = new Error('aborted'); error.name = 'AbortError'; throw error; };
  await assert.rejects(apiRequest('/status'), /timed out/);
  globalThis.fetch = async () => ({...reply(null), json: async () => { throw new Error('invalid JSON'); }});
  await assert.rejects(apiRequest('/status'), /unreadable/);
});

test('capture source is explicit HTTP(S), preserves text, and rejects excessive selections', () => {
  const capture = normalizeCapture({text: '  quoted code\n', url: 'https://example.com/page', title: 'A page', windowId: 3}, 'clip1');
  assert.equal(capture.text, '  quoted code\n');
  assert.equal(capture.windowId, 3);
  for (const url of ['chrome://settings', 'file:///private', 'javascript:alert(1)', 'https://user:pass@example.com/']) assert.throws(() => normalizeCapture({url, windowId: 1}, 'x'));
  assert.throws(() => normalizeCapture({url: 'https://example.com', text: 'x'.repeat(20001), windowId: 1}, 'x'), /nothing was truncated/);
});

test('capture inbox is bounded and never silently discards existing text', () => {
  const current = Array.from({length: 20}, (_, i) => ({id: String(i)}));
  assert.throws(() => appendInbox(current, {id: 'new'}), /inbox is full/);
  assert.equal(current.length, 20);
  assert.equal(appendInbox(current, {id: '1'}).length, 20);
});
