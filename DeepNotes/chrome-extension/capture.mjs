// Pure capture validation shared with the service worker and its tests.
export const MAX_NOTE = 20000;
export const MAX_INBOX = 20;

export function normalizeCapture({text = '', url = '', title = '', windowId, warning = ''}, id = crypto.randomUUID()) {
  let source;
  try { source = new URL(url); } catch { throw new Error('This page cannot be attached. Open a normal web page, then click the DeepNotes toolbar icon again.'); }
  if (!['http:', 'https:'].includes(source.protocol) || source.username || source.password) {
    throw new Error('Only HTTP(S) web pages can be attached. You can still write a note manually.');
  }
  if (typeof text !== 'string' || Array.from(text).length > MAX_NOTE) throw new Error('The selection is too long. Select at most 20,000 characters; nothing was truncated or saved.');
  if (source.href.length > 2000) throw new Error('The page URL is too long to attach. Write a note manually or remove the source.');
  if (!Number.isInteger(windowId) || windowId < 0) throw new Error('The source Chrome window is unavailable.');
  return {id, text, url: source.href, title: Array.from(String(title || source.hostname)).slice(0, 500).join(''), windowId, warning};
}

export function validateWindowId(id) {
  if (!Number.isInteger(id) || id < 0) throw new Error('A valid Chrome window is required.');
  return id;
}

export function appendInbox(existing, capture) {
  const inbox = Array.isArray(existing) ? existing : [];
  if (inbox.some(item => item.id === capture.id)) return inbox;
  if (inbox.length >= MAX_INBOX) throw new Error('Your capture inbox is full. Open DeepNotes and use or dismiss pending captures first.');
  return [...inbox, capture];
}
