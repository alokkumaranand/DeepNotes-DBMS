import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';

let events, data, calls, scriptResult, scriptError;
const id = 'a'.repeat(32);
const url = path => `chrome-extension://${id}/${path}`;
let serial = 0;

beforeEach(async () => {
  events = {}; data = {}; calls = [];
  scriptResult = {text: 'selected text', url: 'https://example.com/document', title: 'Document'};
  scriptError = null;
  const listener = name => ({addListener: callback => { events[name] = callback; }});
  globalThis.chrome = {
    runtime: {id, getURL: url, onInstalled: listener('installed'), onStartup: listener('startup'), onMessage: listener('message')},
    sidePanel: {setPanelBehavior: async options => calls.push(['behavior', options]), open: async options => calls.push(['open', options])},
    action: {setBadgeText: async options => calls.push(['badge', options]), setBadgeBackgroundColor: async () => {}, setTitle: async () => {}},
    storage: {local: {setAccessLevel: async () => {}, get: async key => ({[key]: data[key]}), set: async patch => { Object.assign(data, patch); calls.push(['storage', patch]); }}},
    contextMenus: {onClicked: listener('click'), removeAll: async () => {}, create: options => calls.push(['menu', options])},
    windows: {getLastFocused: async () => ({id: 7})},
    tabs: {query: async options => { calls.push(['query', options]); return [{id: 42, windowId: 7, url: 'https://example.com/old', title: 'Old title'}]; }},
    scripting: {executeScript: async options => { calls.push(['script', options]); if (scriptError) throw scriptError; return [{result: scriptResult}]; }},
  };
  globalThis.fetch = () => { throw new Error('Background worker must never perform network/model calls'); };
  await import(`../background.mjs?test=${serial++}`);
});
function message(payload, sender = {id, url: url('sidepanel.html')}) {
  return new Promise(resolve => {
    assert.equal(events.message(payload, sender, resolve), true);
  });
}

test('toolbar behavior opens native side panel and menu captures only explicit selections', async () => {
  events.installed();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls.find(c => c[0] === 'behavior')[1], {openPanelOnActionClick: true});
  const menu = calls.find(c => c[0] === 'menu')[1];
  assert.deepEqual(menu.contexts, ['selection']);
  assert.deepEqual(menu.documentUrlPatterns, ['http://*/*', 'https://*/*']);
});

test('capture reads selected document and its matching source in the requested window', async () => {
  const result = await message({type: 'capture-current', windowId: 7});
  assert.ok(result.ok);
  assert.equal(result.capture.url, 'https://example.com/document');
  assert.equal(result.capture.title, 'Document');
  assert.equal(result.capture.text, 'selected text');
  assert.deepEqual(calls.find(c => c[0] === 'query')[1], {active: true, windowId: 7});
});

test('restricted selection still permits explicit source attachment with a warning', async () => {
  scriptError = new Error('Cannot access this tab');
  const result = await message({type: 'capture-current', windowId: 7});
  assert.equal(result.ok, true);
  assert.equal(result.capture.text, '');
  assert.match(result.capture.warning, /did not allow/);
});

test('oversized captured text is rejected, never silently clipped', async () => {
  scriptResult.text = 'x'.repeat(20001);
  const result = await message({type: 'capture-current', windowId: 7});
  assert.equal(result.ok, false);
  assert.match(result.error, /nothing was truncated/);
});

test('page/content-script or unknown senders cannot use capture messaging', async () => {
  for (const sender of [{id, url: 'https://evil.example'}, {id: 'b'.repeat(32), url: url('sidepanel.html')}, {}]) {
    const result = await message({type: 'capture-current', windowId: 7}, sender);
    assert.equal(result.ok, false);
  }
  assert.equal(calls.filter(c => c[0] === 'query').length, 0);
});

test('context capture opens synchronously, uses frame source, and is durable until acknowledged', async () => {
  events.click({menuItemId: 'deepnotes-capture-selection', selectionText: 'iframe selection', frameUrl: 'https://frame.example/lecture'}, {windowId: 7, url: 'https://outer.example', title: 'Lecture'});
  assert.equal(calls[0][0], 'open');
  const first = await message({type: 'take-capture', windowId: 7});
  assert.equal(first.capture.url, 'https://frame.example/lecture');
  assert.equal(first.capture.text, 'iframe selection');
  assert.equal((await message({type: 'take-capture', windowId: 7})).capture.id, first.capture.id);
  assert.equal((await message({type: 'take-capture', windowId: 8})).capture, null);
  assert.equal((await message({type: 'ack-capture', windowId: 7, captureId: first.capture.id})).ok, true);
  assert.equal((await message({type: 'take-capture', windowId: 7})).capture, null);
});

test('unrelated right-click menu events are ignored', async () => {
  events.click({menuItemId: 'other', selectionText: 'ignore'}, {windowId: 7});
  assert.equal((await message({type: 'take-capture', windowId: 7})).capture, null);
  assert.equal(calls.filter(c => c[0] === 'open').length, 0);
});
