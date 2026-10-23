import type { components } from './crm-form.d';

/**
 * Публичная форма CRM «Запрос» (M3-CRM-05, M2-CAB-03) — единственный вызов Cabinet мимо портала ERP
 * (CONVENTIONS.md §2.1). Без аутентификации и без cookie: CRM разрешает CORS только origin Cabinet
 * (`CABINET_ORIGIN`) и только на `/api/v1/leads/web*`.
 *
 * - База: `VITE_CRM_URL` (стенд `http://crm.localhost:<HTTP_PORT>`, прод `https://crm.railtech.uz`).
 *   Пусто в dev-сервере — origin страницы: в `make dev` запросы перехватывает MSW, в `make dev-stand`
 *   их проксирует Vite на CRM стенда (CORS не нужен). Пусто в сборке — формы нет, остаётся Telegram.
 * - Ошибка CRM (ADR-0017 CRM): `{"code", "message", "details": {"reason", "field"}}` →
 *   `CrmFormError.code` = `details.reason` или `code`; текст — `newClient.errors.<code>`.
 * - Типы — только сгенерированные из OpenAPI CRM (`src/api/crm-form.d.ts`, `make gen-api-types`).
 */
type Schemas = components['schemas'];
export type WebFormToken = Schemas['WebFormToken'];
export type WebLeadIn = Schemas['WebLeadIn'];
export type WebLeadAccepted = Schemas['WebLeadAccepted'];
type ErrorOut = Schemas['ErrorOut'];

export const CRM_LEAD_FORM_PATH = '/api/v1/leads/web';

export class CrmFormError extends Error {
  readonly status: number;
  /** `details.reason` CRM (`form_too_fast`, `rate_limited`…), иначе `code`; `network` — CRM недоступна. */
  readonly code: string;
  /** Поле формы, к которому относится ошибка (`phone`, `consent`…). */
  readonly field: string | null;

  constructor(status: number, code: string, field: string | null = null) {
    super(`crm ${status} ${code}`);
    this.name = 'CrmFormError';
    this.status = status;
    this.code = code;
    this.field = field;
  }
}

export function isCrmFormError(error: unknown, code?: string): error is CrmFormError {
  return error instanceof CrmFormError && (code === undefined || error.code === code);
}

/** База CRM для формы или `null`, если адрес не задан (форма не показывается, остаётся Telegram). */
export function crmBaseUrl(): string | null {
  const configured = (import.meta.env.VITE_CRM_URL ?? '').trim().replace(/\/+$/, '');
  if (configured) return configured;
  return import.meta.env.DEV ? window.location.origin : null;
}

function isErrorOut(body: unknown): body is ErrorOut {
  return Boolean(body && typeof body === 'object' && 'code' in body && typeof body.code === 'string');
}

async function readError(response: Response): Promise<CrmFormError> {
  try {
    const body: unknown = await response.json();
    if (isErrorOut(body)) {
      const reason = body.details?.reason;
      const field = body.details?.field;
      return new CrmFormError(response.status, reason ?? body.code, typeof field === 'string' ? field : null);
    }
  } catch {
    // Тело не JSON (прокси, 502) — код по статусу ниже.
  }
  return new CrmFormError(response.status, response.status === 429 ? 'rate_limited' : `http_${response.status}`);
}

async function send<T>(path: string, init: { method: 'GET' | 'POST'; body?: unknown }): Promise<T> {
  const base = crmBaseUrl();
  if (!base) throw new CrmFormError(0, 'not_configured');
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (init.body !== undefined) headers['Content-Type'] = 'application/json';
  let response: Response;
  try {
    response = await fetch(`${base}${CRM_LEAD_FORM_PATH}${path}`, {
      method: init.method,
      headers,
      // Форма публичная: cookie CRM не нужны и не должны уходить (CORS без credentials).
      credentials: 'omit',
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    });
  } catch {
    throw new CrmFormError(0, 'network');
  }
  if (!response.ok) throw await readError(response);
  return (await response.json()) as T;
}

/** `GET /api/v1/leads/web/token` — при показе формы; токен уходит в `form_token`. */
export function fetchFormToken(): Promise<WebFormToken> {
  return send<WebFormToken>('/token', { method: 'GET' });
}

/** `POST /api/v1/leads/web` → 202 `{lead_id}` (`null` — отброшено антиспамом, клиенту не говорим). */
export function submitWebLead(body: WebLeadIn): Promise<WebLeadAccepted> {
  return send<WebLeadAccepted>('', { method: 'POST', body });
}
