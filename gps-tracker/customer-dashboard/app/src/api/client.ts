import { clearSession, getSession } from '../auth/session';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

function detail(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d) && d[0]?.msg) return String(d[0].msg).replace(/^Value error, /, '');
  }
  return fallback;
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const token = getSession().token;
  const res = await fetch(path, {
    ...rest,
    headers: {
      ...(json !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (res.status === 401 && token) {
    clearSession();
    onUnauthorized();
  }
  if (res.status === 204) return undefined as T;
  const body = res.headers.get('content-type')?.includes('application/json') ? await res.json() : null;
  if (!res.ok) throw new ApiError(res.status, detail(body, `Request failed (${res.status})`));
  return body as T;
}

/** Download a file response (reports) with the auth header. */
/** Save a file the API returns (a GET, or a POST of `json`). */
export async function download(path: string, fallbackName: string, json?: unknown) {
  const token = getSession().token;
  const res = await fetch(path, {
    method: json === undefined ? 'GET' : 'POST',
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(json === undefined ? {} : { 'Content-Type': 'application/json' }) },
    body: json === undefined ? undefined : JSON.stringify(json),
  });
  if (!res.ok) throw new ApiError(res.status, detail(await res.json().catch(() => null), 'Download failed'));
  const name = /filename="([^"]+)"/.exec(res.headers.get('content-disposition') || '')?.[1] || fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement('a'), { href: url, download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function qs(params: Record<string, string | number | boolean | null | undefined>) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== '') p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : '';
}
