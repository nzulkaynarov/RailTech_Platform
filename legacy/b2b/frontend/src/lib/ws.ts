/**
 * Normalised WebSocket origin for the app.
 *
 * `VITE_WS_URL` is meant to be an ORIGIN only (e.g. `ws://localhost:8000` or
 * `wss://b2b.railtech.uz`). Every caller appends the route itself
 * (`/ws/notifications/`, `/ws/chat/<id>/`). Some envs mistakenly bake a trailing
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
