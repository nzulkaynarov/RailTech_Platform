import type { components, paths } from './portal.d';

/**
 * Клиент портального API ERP `/api/portal/v1` (CONTRACTS §4) — единственный источник данных Cabinet.
 * Типы — только сгенерированные из `packages/contracts/openapi/erp-portal.yaml` (`make gen-api-types`).
 *
 * - База: `VITE_API_URL` (пусто = same-origin; Caddy проксирует `/api/portal/*` на ERP с домена cabinet.*).
 * - Сессия — cookie HttpOnly, поэтому `credentials: 'include'` на каждом запросе.
 * - Каждый POST несёт `Idempotency-Key` (CONTRACTS §0).
 * - Ошибка — `{"detail": "<CODE>"}` → `PortalApiError.code`; текст для человека — `apiErrors.<CODE>` (errors.ts).
 */
export type Schemas = components['schemas'];
export type Me = Schemas['Me'];
export type PortalPath = keyof paths;

export const PORTAL_BASE_PATH = '/api/portal/v1';

export class PortalApiError extends Error {
  readonly status: number;
  /** Код из `{"detail": CODE}`; `NETWORK` — сервер недоступен, `HTTP_<status>` — тело без кода. */
  readonly code: string;

  constructor(status: number, code: string) {
    super(`portal ${status} ${code}`);
    this.name = 'PortalApiError';
    this.status = status;
    this.code = code;
  }
}

export function isPortalApiError(error: unknown, status?: number): error is PortalApiError {
  return error instanceof PortalApiError && (status === undefined || error.status === status);
}

function portalUrl(path: string): string {
  const base = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '');
  // Абсолютный URL от origin страницы: относительные адреса не принимает fetch вне браузера (тесты).
  return new URL(`${base}${PORTAL_BASE_PATH}${path}`, window.location.origin).toString();
}

function newIdempotencyKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function readErrorCode(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
      return body.detail;
    }
  } catch {
    // Тело не JSON (прокси, 502) — код по статусу ниже.
  }
  return `HTTP_${response.status}`;
}

export async function portalRequest<T>(
  path: string,
  { method = 'GET', body }: { method?: 'GET' | 'POST' | 'PUT'; body?: unknown } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (method === 'POST') headers['Idempotency-Key'] = newIdempotencyKey();

  let response: Response;
  try {
    response = await fetch(portalUrl(path), {
      method,
      headers,
      credentials: 'include',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new PortalApiError(0, 'NETWORK');
  }

  if (!response.ok) throw new PortalApiError(response.status, await readErrorCode(response));
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

type JsonBody<Op> = Op extends { requestBody: { content: { 'application/json': infer B } } } ? B : never;

// --- auth и сессия -------------------------------------------------------------------------

export function authTelegram(initData: string): Promise<Me> {
  const body: JsonBody<paths['/auth/telegram']['post']> = { init_data: initData };
  return portalRequest<Me>('/auth/telegram', { method: 'POST', body });
}

export function requestMagicLink(email: string): Promise<void> {
  const body: JsonBody<paths['/auth/magic-link']['post']> = { email };
  return portalRequest<void>('/auth/magic-link', { method: 'POST', body });
}

export function exchangeMagicLink(token: string): Promise<Me> {
  return portalRequest<Me>(`/auth/magic/${encodeURIComponent(token)}`);
}

export function logout(): Promise<void> {
  return portalRequest<void>('/auth/logout', { method: 'POST' });
}

export function getMe(): Promise<Me> {
  return portalRequest<Me>('/me');
}
