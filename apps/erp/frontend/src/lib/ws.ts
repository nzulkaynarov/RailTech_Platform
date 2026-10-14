/**
 * Normalised WebSocket origin for the app.
 *
 * `VITE_WS_URL` is meant to be an ORIGIN only (e.g. `ws://localhost:8000` or
 * `wss://erp.example.com`). Every caller appends the route itself
 * (`/ws/notifications/` — единственный канал после M1-ERP-02 1b). Some envs mistakenly bake a trailing
 * `/ws` into `VITE_WS_URL`, which produced the `/ws/ws/...` double-prefix → 403
 * handshake bug. We defensively strip a trailing slash and a trailing `/ws` so
 * the path is never doubled, regardless of how the env is set.
 */
export function wsBase(): string {
  const env = (import.meta.env.VITE_WS_URL as string | undefined)?.trim();
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  let base = env || `${proto}//${window.location.host}`;
  base = base.replace(/\/+$/, ''); // drop trailing slash(es)
  base = base.replace(/\/ws$/i, ''); // drop a trailing /ws — callers add it
  return base;
}

/**
 * Build an authenticated WebSocket URL for `path` (e.g. `/ws/notifications/`).
 *
 * Mints a short-lived, single-use ticket via POST /auth/ws-ticket/ and puts THAT
 * in the query string instead of the long-lived JWT, so a leaked WS URL (proxy /
 * access logs) is useless within ~30s. Each (re)connect must call this for a
 * fresh ticket. Throws if the ticket can't be minted (caller should retry).
 */
export async function authedWsUrl(path: string): Promise<string> {
  const { apiClient } = await import('@/api/client');
  const { data } = await apiClient.post<{ ticket: string }>('auth/ws-ticket/');
  return `${wsBase()}${path}?ticket=${encodeURIComponent(data.ticket)}`;
}
