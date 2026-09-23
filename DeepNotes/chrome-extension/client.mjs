// Direct panel requests: slow model calls never depend on MV3 worker lifetime.
export const DEFAULT_PORT = 8000;
const ID_PATTERN = /^[a-p]{32}$/;
const READ_ROUTES = new Set(['/status', '/entries', '/structure', '/guidance', '/jobs', '/interactions']);
const WRITE_ROUTES = new Set(['/entries', '/queries', '/guidance', '/structure/reorganize', '/structure/rollback']);

export class ApiError extends Error {
  constructor(message, {status = 0, uncertain = false} = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.uncertain = uncertain;
  }
}

export function validatePort(value) {
  if ((typeof value !== 'number' && typeof value !== 'string') || !/^\d{1,5}$/.test(String(value))) {
    throw new Error('Use a port number from 1 to 65535.');
  }
  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Use a port number from 1 to 65535.');
  return port;
}

export async function loadConfig() {
  const {config} = await chrome.storage.local.get('config');
  try { return {port: validatePort(config?.port ?? DEFAULT_PORT)}; }
  catch { return {port: DEFAULT_PORT}; }
}

export async function saveConfig({port}) {
  const config = {port: validatePort(port)};
  await chrome.storage.local.set({config});
  return config;
}

export function requestURL(path, method, port) {
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//') || /[\\#\r\n]/.test(path)) {
    throw new Error('Invalid DeepNotes API route.');
  }
  const base = `http://127.0.0.1:${validatePort(port)}`;
  const url = new URL('/api' + path, base);
  if (url.origin !== new URL(base).origin || !url.pathname.startsWith('/api/')) throw new Error('Invalid DeepNotes API route.');
  const route = url.pathname.slice(4);
  const allowed = method === 'GET' ? READ_ROUTES.has(route) :
    method === 'POST' && (WRITE_ROUTES.has(route) || /^\/jobs\/[1-9]\d*\/retry$/.test(route));
  if (!allowed || (method !== 'GET' && url.search)) throw new Error('This API operation is not allowed by the extension.');
  return url.href;
}

export async function apiRequest(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const {port} = await loadConfig();
  const url = requestURL(path, method, port);
  const id = chrome.runtime.id;
  if (!ID_PATTERN.test(id || '')) throw new ApiError('Open this interface as the installed Chrome extension.');
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), path === '/queries' ? 270000 : 15000);
  const mutation = method === 'POST';
  let response;
  let submitted = false;
  try {
    if (mutation) {
      // Verify the additive launcher BEFORE any non-idempotent operation. Some
      // extension contexts omit Origin, which the original local API permits.
      const probe = await fetch(new URL('/api/status', url).href, {
        headers: {'Accept': 'application/json', 'X-DeepNotes-Extension': id},
        signal: controller.signal, credentials: 'omit', cache: 'no-store', redirect: 'error',
      });
      if (!probe.ok) {
        const data = await probe.json().catch(() => null);
        throw new ApiError(typeof data?.detail === 'string' ? data.detail : 'Extension connection check failed.', {status: probe.status});
      }
      if (probe.headers.get('X-DeepNotes-Extension-Bridge') !== '1') {
        throw new ApiError('Start the extension-aware launcher shown in Setup before saving notes.');
      }
    }
    submitted = mutation;
    response = await fetch(url, {
      method,
      headers: {'Accept': 'application/json', 'X-DeepNotes-Extension': id,
        ...(mutation ? {'Content-Type': 'application/json'} : {})},
      body: mutation ? JSON.stringify(options.body ?? {}) : undefined,
      signal: controller.signal,
      credentials: 'omit', cache: 'no-store', redirect: 'error',
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = typeof data?.detail === 'string' ? data.detail : `Local API returned HTTP ${response.status}.`;
      throw new ApiError(detail, {status: response.status, uncertain: mutation && response.status >= 500});
    }
    if (response.headers.get('X-DeepNotes-Extension-Bridge') !== '1') {
      throw new ApiError('The regular website backend is running. Start the extension-aware launcher shown in Setup.', {uncertain: mutation});
    }
    if (data === null) throw new ApiError('The local API returned an unreadable response.', {uncertain: mutation});
    return data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    const reason = error?.name === 'AbortError' ? 'The request timed out.' : 'Cannot reach the local DeepNotes backend.';
    throw new ApiError(reason + ' Check that the extension-aware launcher is running, the port matches, and your extension ID is configured.' +
      (submitted ? ' The request may already have been saved; check Library or question history before retrying.' : ''), {uncertain: submitted});
  } finally {
    clearTimeout(timeout);
  }
}
