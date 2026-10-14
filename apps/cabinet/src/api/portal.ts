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

type Method = 'GET' | 'POST' | 'PUT';

async function send(
  path: string,
  { method = 'GET', body, accept = 'application/json' }: { method?: Method; body?: unknown; accept?: string },
): Promise<Response> {
  const headers: Record<string, string> = { Accept: accept };
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
  return response;
}

export async function portalRequest<T>(
  path: string,
  { method = 'GET', body }: { method?: Method; body?: unknown } = {},
): Promise<T> {
  const response = await send(path, { method, body });
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

/** Строка запроса из параметров; пустые значения не передаются. */
function toQuery(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
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

// --- разделы кабинета (M2-CAB-02) ----------------------------------------------------------

type QueryOf<Op> = Op extends { parameters: { query?: infer Q } } ? NonNullable<Q> : never;

export type Money = Schemas['Money'];
export type ClientRequest = Schemas['ClientRequest'];
export type ClientRequestCreate = Schemas['ClientRequestCreate'];
export type RequestLineIn = Schemas['RequestLineIn'];
export type QuoteListItem = Schemas['QuoteListItem'];
export type Quote = Schemas['Quote'];
export type QuoteLine = Schemas['QuoteLine'];
export type Contract = Schemas['Contract'];
export type Invoice = Schemas['Invoice'];
export type Act = Schemas['Act'];
export type DeliveryLine = Schemas['DeliveryLine'];
export type PortalDocument = Schemas['Document'];
export type DocumentKind = Schemas['DocumentKind'];
export type CatalogItem = Schemas['CatalogItem'];
export type CatalogPage = Schemas['CatalogPage'];
export type CatalogQuery = QueryOf<paths['/catalog']['get']>;
export type DocumentsQuery = QueryOf<paths['/documents']['get']>;
export type Company = Schemas['Company'];
export type CompanyUpdate = Schemas['CompanyUpdate'];
export type TeamMember = Schemas['TeamMember'];
export type TeamInvite = Schemas['TeamInvite'];

export const listRequests = () => portalRequest<ClientRequest[]>('/requests');
export function createRequest(body: JsonBody<paths['/requests']['post']>): Promise<ClientRequest> {
  return portalRequest<ClientRequest>('/requests', { method: 'POST', body });
}

export const listQuotes = () => portalRequest<QuoteListItem[]>('/quotes');
export const getQuote = (id: number) => portalRequest<Quote>(`/quotes/${id}`);
export function acceptQuote(id: number, code: string): Promise<Quote> {
  const body: JsonBody<paths['/quotes/{id}/accept']['post']> = { code };
  return portalRequest<Quote>(`/quotes/${id}/accept`, { method: 'POST', body });
}
export function rejectQuote(id: number, reason: string): Promise<Quote> {
  const body: JsonBody<paths['/quotes/{id}/reject']['post']> = { reason };
  return portalRequest<Quote>(`/quotes/${id}/reject`, { method: 'POST', body });
}

export const listContracts = () => portalRequest<Contract[]>('/contracts');
export const signContract = (id: number) => portalRequest<Contract>(`/contracts/${id}/sign`, { method: 'POST' });

export const listInvoices = () => portalRequest<Invoice[]>('/invoices');

export const listActs = () => portalRequest<Act[]>('/acts');
export const acceptAct = (id: number) => portalRequest<Act>(`/acts/${id}/accept`, { method: 'POST' });
export function returnAct(id: number, reason: string): Promise<Act> {
  const body: JsonBody<paths['/acts/{id}/return']['post']> = { reason };
  return portalRequest<Act>(`/acts/${id}/return`, { method: 'POST', body });
}

export const listDeliveries = () => portalRequest<DeliveryLine[]>('/deliveries');

export const listDocuments = (params: DocumentsQuery = {}) =>
  portalRequest<PortalDocument[]>(`/documents${toQuery(params)}`);

/**
 * Файл документа: 200 — содержимое; 202 — PDF ещё рендерится, повторить через `Retry-After`
 * секунд (контракт, M2-ERP-03). Опрос и сохранение — `lib/download.ts`.
 */
export type DocumentFile =
  | { state: 'ready'; blob: Blob; fileName: string | null }
  | { state: 'pending'; retryAfterSeconds: number };

export const DEFAULT_RETRY_AFTER_SECONDS = 2;

export async function getDocumentFile(id: number): Promise<DocumentFile> {
  const response = await send(`/documents/${id}/file`, { accept: 'application/pdf, application/octet-stream' });
  if (response.status === 202) {
    const header = Number(response.headers.get('Retry-After'));
    return { state: 'pending', retryAfterSeconds: header >= 1 ? header : DEFAULT_RETRY_AFTER_SECONDS };
  }
  return {
    state: 'ready',
    blob: await response.blob(),
    fileName: fileNameFrom(response.headers.get('Content-Disposition')),
  };
}

function fileNameFrom(disposition: string | null): string | null {
  if (!disposition) return null;
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1]);
    } catch {
      // Битое кодирование — берём простое имя ниже.
    }
  }
  return /filename="?([^";]+)"?/i.exec(disposition)?.[1] ?? null;
}

export const listCatalog = (params: CatalogQuery = {}) => portalRequest<CatalogPage>(`/catalog${toQuery(params)}`);
export const getCatalogItem = (id: number) => portalRequest<CatalogItem>(`/catalog/${id}`);

export const getCompany = () => portalRequest<Company>('/company');
export const updateCompany = (body: CompanyUpdate) => portalRequest<Company>('/company', { method: 'PUT', body });
export const listTeam = () => portalRequest<TeamMember[]>('/team');
export const inviteTeamMember = (body: TeamInvite) =>
  portalRequest<TeamMember>('/team/invite', { method: 'POST', body });
