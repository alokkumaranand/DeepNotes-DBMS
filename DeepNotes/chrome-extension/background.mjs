import {normalizeCapture, validateWindowId, appendInbox} from './capture.mjs';

const MENU_ID = 'deepnotes-capture-selection';
let storageQueue = Promise.resolve();

// Serialize read-modify-write capture operations during this worker's lifetime.
function serialized(task) {
  const result = storageQueue.then(task, task);
  storageQueue = result.catch(() => {});
  return result;
}

async function configure() {
  await chrome.sidePanel.setPanelBehavior({openPanelOnActionClick: true});
  await chrome.storage.local.setAccessLevel({accessLevel: 'TRUSTED_CONTEXTS'});
}

async function report(error) {
  const message = error?.message || 'Capture failed. Open the panel and try again.';
  // Badge/title are local feedback only: never silently save a failed capture.
  await chrome.action.setBadgeText({text: '!'}).catch(() => {});
  await chrome.action.setBadgeBackgroundColor({color: '#b45309'}).catch(() => {});
  await chrome.action.setTitle({title: `DeepNotes: ${message}`}).catch(() => {});
  await chrome.storage.local.set({captureError: message}).catch(() => {});
}

chrome.runtime.onInstalled.addListener(() => {
  configure().catch(report);
  chrome.contextMenus.removeAll().then(() => chrome.contextMenus.create({
    id: MENU_ID, title: 'Send selection to DeepNotes', contexts: ['selection'],
    documentUrlPatterns: ['http://*/*', 'https://*/*'],
  })).catch(report);
});
chrome.runtime.onStartup.addListener(() => { configure().catch(report); });

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== MENU_ID || !tab) return;
  // Must be invoked synchronously within the user gesture, before storage awaits.
  chrome.sidePanel.open({windowId: tab.windowId}).catch(report);
  serialized(async () => {
    const capture = normalizeCapture({text: info.selectionText || '', url: info.frameUrl || info.pageUrl || tab.url,
      title: tab.title, windowId: tab.windowId});
    const key = `inbox:${capture.windowId}`;
    const stored = await chrome.storage.local.get(key);
    await chrome.storage.local.set({[key]: appendInbox(stored[key], capture)});
    await chrome.action.setBadgeText({text: ''});
    await chrome.action.setTitle({title: 'Open DeepNotes'});
  }).catch(report);
});

async function captureCurrent(windowId) {
  if (windowId == null) windowId = (await chrome.windows.getLastFocused()).id;
  validateWindowId(windowId);
  const [tab] = await chrome.tabs.query({active: true, windowId});
  if (!tab || !tab.url) throw new Error('Click the DeepNotes toolbar icon on the tab you want to capture, then try again.');
  // Validate the source before attempting injection into protected Chrome pages.
  const source = normalizeCapture({url: tab.url, title: tab.title, windowId});
  try {
    const result = await chrome.scripting.executeScript({
      target: {tabId: tab.id},
      func: () => ({text: window.getSelection()?.toString() || '', url: location.href, title: document.title}),
    });
    // Read selection AND source inside the same document to avoid navigation races.
    const documentCapture = result?.[0]?.result;
    if (!documentCapture || typeof documentCapture.url !== 'string') throw new Error('The page changed during capture.');
    return normalizeCapture({...documentCapture, windowId});
  } catch (error) {
    // Explicit size/source validation errors should not become a silent empty capture.
    if (error?.message?.includes('nothing was truncated') || error?.message?.includes('URL is too long')) throw error;
    return {...source, text: '', warning: 'Page attached, but Chrome did not allow reading its selection. For embedded text, use the right-click selection menu. You can also paste text manually.'};
  }
}

function trustedPanel(sender) {
  return sender.id === chrome.runtime.id && typeof sender.url === 'string' &&
    sender.url.split(/[?#]/)[0] === chrome.runtime.getURL('sidepanel.html');
}

async function handleMessage(message, sender) {
  if (!trustedPanel(sender)) throw new Error('Only the DeepNotes side panel can request capture.');
  if (message?.type === 'capture-current') return {ok: true, capture: await captureCurrent(message.windowId)};
  if (message?.type === 'take-capture') {
    const windowId = validateWindowId(message.windowId);
    return serialized(async () => {
      const key = `inbox:${windowId}`;
      const stored = await chrome.storage.local.get(key);
      const inbox = Array.isArray(stored[key]) ? stored[key] : [];
      return {ok: true, capture: inbox[0] || null};
    });
  }
  if (message?.type === 'ack-capture') {
    const windowId = validateWindowId(message.windowId);
    if (typeof message.captureId !== 'string') throw new Error('A capture ID is required.');
    return serialized(async () => {
      const key = `inbox:${windowId}`;
      const stored = await chrome.storage.local.get(key);
      const inbox = Array.isArray(stored[key]) ? stored[key] : [];
      await chrome.storage.local.set({[key]: inbox.filter(item => item.id !== message.captureId)});
      return {ok: true};
    });
  }
  throw new Error('Unknown DeepNotes browser action.');
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message, sender).then(sendResponse, error => sendResponse({ok: false, error: error.message || 'Capture failed.'}));
  return true; // Short Chrome API work only. No model calls are proxied through here.
});
