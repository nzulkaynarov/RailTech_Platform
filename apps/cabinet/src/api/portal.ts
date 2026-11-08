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
  /** Заголовок `Retry-After` (429), секунды; `null` — заголовка нет или он не разобран. */
  readonly retryAfter: number | null;

  constructor(status: number, code: string, retryAfter: number | null = null) {
    super(`portal ${status} ${code}`);
    this.name = 'PortalApiError';
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
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

/** `Retry-After`: целые секунды или HTTP-дата (RFC 9110 §10.2.3); непонятное значение — `null`. */
export function parseRetryAfter(value: string | null, now: number = Date.now()): number | null {
  const text = value?.trim();
  if (!text) return null;
  if (/^\d+$/.test(text)) return Number(text);
  const at = Date.parse(text);
  return Number.isNaN(at) ? null : Math.max(0, Math.ceil((at - now) / 1000));
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

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

  if (!response.ok) {
    throw new PortalApiError(response.status, await readErrorCode(response), parseRetryAfter(response.headers.get('Retry-After')));
  }
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

export interface MagicLinkResult {
  status: 'ok' | 'not_registered';
  sent: boolean;
  email: string;
}

export function requestMagicLink(email: string): Promise<MagicLinkResult> {
  const body = { email };
  return portalRequest<MagicLinkResult>('/auth/magic-link', { method: 'POST', body });
}

export interface PortalCountry {
  code: string;
  name: string;
  alpha3?: string;
  phone_code: string;
  phone_mask: string;
  phone_placeholder: string;
  tax_label: string;
  tax_placeholder: string;
  tax_regex?: string;
  is_uzbekistan: boolean;
}

export function getPortalCountries(): Promise<PortalCountry[]> {
  return portalRequest<PortalCountry[]>('/countries');
}

/** Обмен токена из ссылки входа на сессию; токен — в теле, не в пути (FIX-20: пути попадают в журналы). */
export function exchangeMagicToken(token: string): Promise<Me> {
  const body: JsonBody<paths['/auth/magic']['post']> = { token };
  return portalRequest<Me>('/auth/magic', { method: 'POST', body });
}

/** Вход по 6-значному коду из письма входа или приглашения (B-MAIL-1): адрес и код → сессия. */
export function exchangeLoginCode(email: string, code: string): Promise<Me> {
  const body: JsonBody<paths['/auth/code']['post']> = { email, code };
  return portalRequest<Me>('/auth/code', { method: 'POST', body });
}

export function logout(): Promise<void> {
  return portalRequest<void>('/auth/logout', { method: 'POST' });
}

export function listSessions(): Promise<PortalSessionItem[]> {
  return portalRequest<PortalSessionItem[]>('/auth/sessions');
}

export function revokeOtherSessions(): Promise<{ revoked_count: number }> {
  return portalRequest<{ revoked_count: number }>('/auth/sessions/revoke-others', { method: 'POST' });
}

export function getMe(): Promise<Me> {
  return portalRequest<Me>('/me');
}

// --- Telegram контакта (ADR-0023 п. 3, NOTIFY-1) ----------------------------------------------

export type TelegramStatus = Schemas['TelegramStatus'];
export type TelegramLink = Schemas['TelegramLink'];

/** Привязан ли Telegram (по проекции CRM) и можно ли выпустить ссылку привязки. */
export const getTelegramStatus = () => portalRequest<TelegramStatus>('/me/telegram');
/** Одноразовая ссылка `t.me/<бот>?start=<токен>` на 15 минут; тело пустое (`{}`), ответ 201. */
export const createTelegramLink = () => portalRequest<TelegramLink>('/me/telegram-link', { method: 'POST', body: {} });
/** Отключить Telegram: ERP просит CRM отвязать (202); `linked` станет `false`, когда придёт проекция. */
export const unlinkTelegram = () => portalRequest<TelegramStatus>('/me/telegram', { method: 'DELETE' });
/**
 * Проверочное сообщение в привязанный Telegram: ERP просит бот CRM написать контакту (202). Не чаще раза в минуту —
 * иначе 429 с `Retry-After` (`PortalApiError.retryAfter`); не привязан — 409 `TELEGRAM_NOT_LINKED`.
 */
export const sendTelegramTest = () =>
  portalRequest<TelegramStatus>('/me/telegram/test', { method: 'POST', body: {} });

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
export type PaymentProof = Schemas['PaymentProof'];
export type PaymentProofCreate = Schemas['PaymentProofCreate'];
export type QuoteComment = Schemas['QuoteComment'];
export type Act = Schemas['Act'];
export type DealRef = Schemas['DealRef'];
export type AcceptanceCodeSent = Schemas['AcceptanceCodeSent'];
export type DeliveryLine = Schemas['DeliveryLine'];
export type PortalDocument = Schemas['Document'];
export type DocumentKind = Schemas['DocumentKind'];
export type AttachmentRef = Schemas['AttachmentRef'];
export type CatalogCategory = Schemas['CatalogCategory'];
export type PortalUploadResponse = Schemas['PortalUploadResponse'];
export type CatalogItem = Schemas['CatalogItem'];
export type CatalogItemDocument = Schemas['CatalogItemDocument'];
export type CatalogPage = Schemas['CatalogPage'];
export type CatalogQuery = QueryOf<paths['/catalog']['get']>;
export type DocumentsQuery = QueryOf<paths['/documents']['get']>;
export type Company = Schemas['Company'];
export type CompanyUpdate = Schemas['CompanyUpdate'];
export type CompanySecurityLogResponse = Schemas['CompanySecurityLogResponse'];
export type CompanySecurityLogItem = Schemas['CompanySecurityLogItem'];
export type PortalRelationshipStatus = Schemas['PortalRelationshipStatus'];
export type PortalRelationship = Schemas['PortalRelationship'];
export type TeamMember = Schemas['TeamMember'];
export type TeamMemberUpdate = Schemas['TeamMemberUpdate'];
export type TeamInvite = Schemas['TeamInvite'];
export type PortalSessionItem = Schemas['PortalSessionItem'];
export type RequestsQuery = QueryOf<paths['/requests']['get']>;

export const listRequests = (params: RequestsQuery = {}) =>
  portalRequest<ClientRequest[]>(`/requests${toQuery(params)}`);
export const getRequest = (id: number) => portalRequest<ClientRequest>(`/requests/${id}`);
export function createRequest(body: JsonBody<paths['/requests']['post']>): Promise<ClientRequest> {
  return portalRequest<ClientRequest>('/requests', { method: 'POST', body });
}
export function reorderRequest(id: number): Promise<ClientRequest> {
  return portalRequest<ClientRequest>(`/requests/${id}/reorder`, { method: 'POST' });
}

export const listQuotes = () => portalRequest<QuoteListItem[]>('/quotes');
export const getQuote = (id: number) => portalRequest<Quote>(`/quotes/${id}`);
/** Код акцепта ERP шлёт контакту сам (Telegram или e-mail) — мастер-кода нет; ответ — канал и замаскированный адрес. */
export function requestQuoteCode(id: number): Promise<AcceptanceCodeSent> {
  return portalRequest<AcceptanceCodeSent>(`/quotes/${id}/request-code`, { method: 'POST' });
}
export function acceptQuote(id: number, code: string): Promise<Quote> {
  const body: JsonBody<paths['/quotes/{id}/accept']['post']> = { code };
  return portalRequest<Quote>(`/quotes/${id}/accept`, { method: 'POST', body });
}
/** Комментарий к КП, пока оно ждёт решения; ответ — комментарий, лента — `Quote.comments`. */
export function addQuoteComment(id: number, text: string): Promise<QuoteComment> {
  const body: JsonBody<paths['/quotes/{id}/comments']['post']> = { text };
  return portalRequest<QuoteComment>(`/quotes/${id}/comments`, { method: 'POST', body });
}
export function rejectQuote(id: number, reason: string): Promise<Quote> {
  const body: JsonBody<paths['/quotes/{id}/reject']['post']> = { reason };
  return portalRequest<Quote>(`/quotes/${id}/reject`, { method: 'POST', body });
}

export const listContracts = () => portalRequest<Contract[]>('/contracts');
export const signContract = (id: number) => portalRequest<Contract>(`/contracts/${id}/sign`, { method: 'POST' });

export const listInvoices = () => portalRequest<Invoice[]>('/invoices');
/** «Я оплатил»: платёжное поручение (`upload_id` из `POST /uploads`) к счёту; ответ — платёжка `pending`. */
export function submitPaymentProof(id: number, body: PaymentProofCreate): Promise<PaymentProof> {
  return portalRequest<PaymentProof>(`/invoices/${id}/proofs`, { method: 'POST', body });
}

export const listActs = () => portalRequest<Act[]>('/acts');
/** Приёмка акта; скан подписанного экземпляра (`upload_id` из `POST /uploads`) необязателен. */
export function acceptAct(id: number, uploadId?: string): Promise<Act> {
  const body: Schemas['ActAccept'] | undefined = uploadId ? { upload_id: uploadId } : undefined;
  return portalRequest<Act>(`/acts/${id}/accept`, { method: 'POST', body });
}
export function returnAct(id: number, reason: string): Promise<Act> {
  const body: JsonBody<paths['/acts/{id}/return']['post']> = { reason };
  return portalRequest<Act>(`/acts/${id}/return`, { method: 'POST', body });
}

export const listDeliveries = () => portalRequest<DeliveryLine[]>('/deliveries');
export const acceptDelivery = (id: number) => portalRequest<DeliveryLine>(`/deliveries/${id}/accept`, { method: 'POST' });
export function disputeDelivery(id: number, reason: string): Promise<DeliveryLine> {
  const body: JsonBody<paths['/deliveries/{id}/dispute']['post']> = { reason };
  return portalRequest<DeliveryLine>(`/deliveries/${id}/dispute`, { method: 'POST', body });
}

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

// --- «Мои товары» партнёра (модуль `my_products`, PART-2) ------------------------------------

export type PartnerProduct = Schemas['PartnerProduct'];
export type PartnerProductDetail = Schemas['PartnerProductDetail'];
export type PartnerProductPage = Schemas['PartnerProductPage'];
export type PartnerProductDocument = Schemas['PartnerProductDocument'];
export type PartnerDocumentUploadRequest = Schemas['PartnerDocumentUploadRequest'];
export type PartnerCardStatus = Schemas['PartnerCardStatus'];
export type PartnerOffer = Schemas['PartnerOffer'];
export type OfferFreshness = Schemas['OfferFreshness'];
export type PartnerIssue = Schemas['PartnerIssue'];
export type PartnerSubmitResult = Schemas['PartnerSubmitResult'];
export type PartnerConfirmResult = Schemas['PartnerConfirmResult'];
export type PartnerConfirmRequest = Schemas['PartnerConfirmRequest'];
export type PriceListTask = Schemas['PriceListTask'];
export type PriceListReport = Schemas['PriceListReport'];
export type PriceListRowIssue = Schemas['PriceListRowIssue'];
export type PartnerProductsQuery = QueryOf<paths['/partner/products']['get']>;

export const listPartnerProducts = (params: PartnerProductsQuery = {}) =>
  portalRequest<PartnerProductPage>(`/partner/products${toQuery(params)}`);
export const getPartnerProduct = (id: number) => portalRequest<PartnerProductDetail>(`/partner/products/${id}`);

export const listPartnerProductDocuments = (productId: number) =>
  portalRequest<PartnerProductDocument[]>(`/partner/products/${productId}/documents`);

export async function uploadPartnerProductDocument(
  productId: number,
  data: {
    file?: File;
    upload_id?: number;
    kind?: string;
    title: string;
    number?: string;
    issued_by?: string;
    issued_at?: string;
    valid_until?: string;
  },
): Promise<PartnerProductDocument> {
  if (data.file) {
    const formData = new FormData();
    formData.append('file', data.file);
    if (data.kind) formData.append('kind', data.kind);
    formData.append('title', data.title);
    if (data.number) formData.append('number', data.number);
    if (data.issued_by) formData.append('issued_by', data.issued_by);
    if (data.issued_at) formData.append('issued_at', data.issued_at);
    if (data.valid_until) formData.append('valid_until', data.valid_until);
    const response = await postForm(`/partner/products/${productId}/documents`, formData);
    return (await response.json()) as PartnerProductDocument;
  }
  return portalRequest<PartnerProductDocument>(`/partner/products/${productId}/documents`, {
    method: 'POST',
    body: {
      upload_id: data.upload_id ? String(data.upload_id) : undefined,
      kind: data.kind,
      title: data.title,
      number: data.number,
      issued_by: data.issued_by,
      issued_at: data.issued_at,
      valid_until: data.valid_until,
    },
  });
}

export const deletePartnerProductDocument = (productId: number, docId: number) =>
  portalRequest<void>(`/partner/products/${productId}/documents/${docId}`, { method: 'DELETE' });

export async function getPartnerProductDocumentFile(
  productId: number,
  documentId: number,
): Promise<{ blob: Blob; fileName: string | null }> {
  const response = await send(`/partner/products/${productId}/documents/${documentId}/file`, {
    accept: 'application/pdf, image/png, image/jpeg, application/octet-stream',
  });
  return { blob: await response.blob(), fileName: fileNameFrom(response.headers.get('Content-Disposition')) };
}

export function submitPartnerProducts(ids: number[]): Promise<PartnerSubmitResult> {
  const body: JsonBody<paths['/partner/products/submit']['post']> = { ids };
  return portalRequest<PartnerSubmitResult>('/partner/products/submit', { method: 'POST', body });
}
export function confirmPartnerOffers(body: PartnerConfirmRequest): Promise<PartnerConfirmResult> {
  return portalRequest<PartnerConfirmResult>('/partner/offers/confirm', { method: 'POST', body });
}
export const getPriceListTask = (taskId: string) =>
  portalRequest<PriceListTask>(`/partner/price-list/${encodeURIComponent(taskId)}`);

const XLSX_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

/** Шаблон прайса — тот же файл, что у сотрудника; в браузере сохраняется как `price-template.xlsx`. */
export async function getPriceTemplate(): Promise<Blob> {
  const response = await send('/partner/price-template', { accept: XLSX_TYPE });
  return response.blob();
}

export interface PriceListUpload {
  file: File;
  /** Предпросмотр: проверка и отчёт без записи. */
  dryRun: boolean;
  /** Срок действия цен на весь файл, `ГГГГ-ММ-ДД`; пусто — как в колонках файла или без срока. */
  validFrom?: string;
  validUntil?: string;
}

/** Загрузка прайса (`multipart/form-data`): 202 и `task_id`, состояние — `getPriceListTask`. */
export async function uploadPriceList({ file, dryRun, validFrom, validUntil }: PriceListUpload): Promise<string> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('dry_run', String(dryRun));
  if (validFrom) formData.append('valid_from', validFrom);
  if (validUntil) formData.append('valid_until', validUntil);
  const response = await postForm('/partner/price-list', formData);
  return ((await response.json()) as Schemas['PriceListAccepted']).task_id;
}

export const listCatalog = (params: CatalogQuery = {}) => portalRequest<CatalogPage>(`/catalog${toQuery(params)}`);
export const listCatalogCategories = () => portalRequest<CatalogCategory[]>('/catalog/categories');
export const getCatalogItem = (id: number) => portalRequest<CatalogItem>(`/catalog/${id}`);

/**
 * Файл документа карточки `GET /catalog/{id}/documents/{doc_id}/file` (CAT-CARD-2): отдаётся сразу, без рендера и 202.
 * Имя файла сервер строит из названия документа; своего имени Cabinet не придумывает, кроме запасного.
 */
export async function getCatalogItemDocumentFile(
  itemId: number,
  documentId: number,
): Promise<{ blob: Blob; fileName: string | null }> {
  const response = await send(`/catalog/${itemId}/documents/${documentId}/file`, {
    accept: 'application/pdf, image/png, image/jpeg, application/octet-stream',
  });
  return { blob: await response.blob(), fileName: fileNameFrom(response.headers.get('Content-Disposition')) };
}

/** `POST multipart/form-data` с ключом попытки; ошибка — `PortalApiError` с кодом из `{"detail": CODE}`. */
async function postForm(path: string, formData: FormData): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(portalUrl(path), {
      method: 'POST',
      headers: { Accept: 'application/json', 'Idempotency-Key': newIdempotencyKey() },
      credentials: 'include',
      body: formData,
    });
  } catch {
    throw new PortalApiError(0, 'NETWORK');
  }
  if (!response.ok) {
    throw new PortalApiError(response.status, await readErrorCode(response), parseRetryAfter(response.headers.get('Retry-After')));
  }
  return response;
}

export async function uploadFile(file: File): Promise<PortalUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  const response = await postForm('/uploads', formData);
  return (await response.json()) as PortalUploadResponse;
}

// --- чат кабинета (CHAT-1, ADR-0023) -------------------------------------------------------

export type PortalMessage = Schemas['PortalMessage'];
export type PortalMessagePage = Schemas['PortalMessagePage'];
export type PortalMessageCreate = Schemas['PortalMessageCreate'];
export type MessageContext = Schemas['MessageContext'];
export type MessageContextKind = Schemas['MessageContextKind'];
export type MessagesQuery = QueryOf<paths['/messages']['get']>;

/** Лента компании по возрастанию `id`: с `after_id` — новые после него (опрос), без — последние `limit`. */
export const listMessages = (params: MessagesQuery = {}) =>
  portalRequest<PortalMessagePage>(`/messages${toQuery(params)}`);
/** Сообщение менеджеру: повтор с тем же `client_message_id` возвращает прежнее (ERP не создаёт второе). */
export const postMessage = (body: PortalMessageCreate) =>
  portalRequest<PortalMessage>('/messages', { method: 'POST', body });
/** Контакт прочитал ленту до `last_id`; ответ — сколько ответов менеджера осталось непрочитанными. */
export function markMessagesRead(lastId: number): Promise<Schemas['PortalMessageUnread']> {
  const body: JsonBody<paths['/messages/read']['post']> = { last_id: lastId };
  return portalRequest<Schemas['PortalMessageUnread']>('/messages/read', { method: 'POST', body });
}

export const getCompany = () => portalRequest<Company>('/company');
export const updateCompany = (body: CompanyUpdate) => portalRequest<Company>('/company', { method: 'PUT', body });
export const getCompanySecurityLog = () =>
  portalRequest<CompanySecurityLogResponse>('/company/security-log');
export const listTeam = () => portalRequest<TeamMember[]>('/team');
export const inviteTeamMember = (body: TeamInvite) =>
  portalRequest<TeamMember>('/team/invite', { method: 'POST', body });
export const updateTeamMember = (id: number, body: TeamMemberUpdate) =>
  portalRequest<TeamMember>(`/team/${id}`, { method: 'PATCH', body });
export const deactivateTeamMember = (id: number) =>
  portalRequest<{ ok: boolean; deactivated_contact_id: number }>(`/team/${id}/deactivate`, { method: 'POST' });

// --- колокольчик кабинета (NOTIFY-2, ADR-0023 п. 2) ---------------------------------------------

export type PortalNotification = Schemas['PortalNotification'];
export type NotificationPage = Schemas['NotificationPage'];
export type NotificationKind = Schemas['NotificationKind'];
export type NotificationGroup = Schemas['NotificationGroup'];
export type NotificationsQuery = QueryOf<paths['/notifications']['get']>;

export const listNotifications = (params: NotificationsQuery = {}) =>
  portalRequest<NotificationPage>(`/notifications${toQuery(params)}`);

/** «Прочитано»: свои `ids` или все (`all: true`); ответ — число непрочитанных для бейджа. */
export function markNotificationsRead(body: JsonBody<paths['/notifications/read']['post']>) {
  return portalRequest<Schemas['NotificationUnread']>('/notifications/read', { method: 'POST', body });
}

// --- настройки каналов уведомлений (Wave J3, ADR-0023) -------------------------------------------

export type NotificationSettingsResponse = Schemas['NotificationSettingsResponse'];
export type NotificationSettingsUpdate = Schemas['NotificationSettingsUpdate'];
export type NotificationGroupSettingsMap = Schemas['NotificationGroupSettingsMap'];
export type NotificationChannelSettings = Schemas['NotificationChannelSettings'];

export const getNotificationSettings = () =>
  portalRequest<NotificationSettingsResponse>('/notifications/settings');

export const updateNotificationSettings = (body: NotificationSettingsUpdate) =>
  portalRequest<NotificationSettingsResponse>('/notifications/settings', { method: 'PATCH', body });

// --- публичная проверка официальных документов (ADR-0024 §6, SIGN-VERIFY-1) -----------------------

export type DocumentVerification = Schemas['DocumentVerification'];
export type DocumentVerificationKind = Schemas['DocumentVerificationKind'];

export const verifyDocument = (code: string) =>
  portalRequest<DocumentVerification>(`/verify/${encodeURIComponent(code)}`);

// --- заявки кандидатов в партнёры (ADR-0022, DECISIONS 2026-11-05, PART-ONBOARD-1) --------------

export type PartnerKind = Schemas['PartnerKind'];
export type PartnerApplicationStatus = Schemas['PartnerApplicationStatus'];
export type PartnerApplication = Schemas['PartnerApplication'];
export type PartnerApplicationPublicCreate = Schemas['PartnerApplicationPublicCreate'];
export type PartnerApplicationPublicResult = Schemas['PartnerApplicationPublicResult'];
export type PartnerApplicationClientCreate = Schemas['PartnerApplicationClientCreate'];
export type PartnerApplicationStatusResponse = Schemas['PartnerApplicationStatusResponse'];

/** Публичная подача заявки «Стать партнёром» поставщиком/производителем. */
export const submitPartnerApplication = (body: PartnerApplicationPublicCreate) =>
  portalRequest<PartnerApplicationPublicResult>('/auth/partner-application', { method: 'POST', body });

/** Статус заявки действующего клиента на получение роли партнёра. */
export const getCompanyPartnerApplication = () =>
  portalRequest<PartnerApplicationStatusResponse>('/company/partner-application');

/** Подача заявки действующим клиентом из личного кабинета. */
export const submitCompanyPartnerApplication = (body: PartnerApplicationClientCreate) =>
  portalRequest<PartnerApplication>('/company/partner-application', { method: 'POST', body });

/** URL для скачивания PDF договора кандидата. */
export const getPartnerContractPdfUrl = () => portalUrl('/company/partner-application/contract-pdf');

/** Согласование проекта партнёрского договора кандидатом. */
export const agreeCompanyPartnerContract = (body?: { notes?: string }) =>
  portalRequest<PartnerApplication>('/company/partner-application/agree', { method: 'POST', body: body ?? {} });

// --- заказы партнёра и запросы цен (K2-orders) ----------------------------------------------------

export type PartnerOrderStatus = Schemas['PartnerOrderStatus'];
export type PartnerOrderListItem = Schemas['PartnerOrderListItem'];
export type PartnerOrderStatusCounts = Schemas['PartnerOrderStatusCounts'];
export type PartnerOrderPage = Schemas['PartnerOrderPage'];
export type PartnerOrderLineItem = Schemas['PartnerOrderLineItem'];
export type PartnerOrderLogItem = Schemas['PartnerOrderLogItem'];
export type PartnerOrderReceiptItem = Schemas['PartnerOrderReceiptItem'];
export type PartnerOrderReceiptLineItem = Schemas['PartnerOrderReceiptLineItem'];
export type PartnerOrderDetail = Schemas['PartnerOrderDetail'];
export type PartnerOrderConfirmRequest = Schemas['PartnerOrderConfirmRequest'];
export type PartnerShipmentNoticeRequest = Schemas['PartnerShipmentNoticeRequest'];

export type PartnerOrdersQuery = QueryOf<paths['/partner/orders']['get']>;

export const listPartnerOrders = (params: PartnerOrdersQuery = {}) =>
  portalRequest<PartnerOrderPage>(`/partner/orders${toQuery(params)}`);

export const getPartnerOrder = (id: number) =>
  portalRequest<PartnerOrderDetail>(`/partner/orders/${id}`);

export const confirmPartnerOrder = (id: number, body?: PartnerOrderConfirmRequest) =>
  portalRequest<PartnerOrderDetail>(`/partner/orders/${id}/confirm`, { method: 'POST', body: body ?? {} });

export const shipPartnerOrder = (id: number, body: PartnerShipmentNoticeRequest) =>
  portalRequest<PartnerOrderDetail>(`/partner/orders/${id}/ship`, { method: 'POST', body });

export type PartnerPriceRequestStatus = Schemas['PartnerPriceRequestStatus'];
export type PartnerPriceRequestListItem = Schemas['PartnerPriceRequestListItem'];
export type PartnerPriceRequestStatusCounts = Schemas['PartnerPriceRequestStatusCounts'];
export type PartnerPriceRequestPage = Schemas['PartnerPriceRequestPage'];
export type PartnerPriceRequestLineItem = Schemas['PartnerPriceRequestLineItem'];
export type PartnerPriceRequestDetail = Schemas['PartnerPriceRequestDetail'];
export type PartnerPriceRequestResponse = Schemas['PartnerPriceRequestResponse'];

export type PartnerPriceRequestsQuery = QueryOf<paths['/partner/price-requests']['get']>;

export const listPartnerPriceRequests = (params: PartnerPriceRequestsQuery = {}) =>
  portalRequest<PartnerPriceRequestPage>(`/partner/price-requests${toQuery(params)}`);

export const getPartnerPriceRequest = (id: number) =>
  portalRequest<PartnerPriceRequestDetail>(`/partner/price-requests/${id}`);

export const respondPartnerPriceRequest = (id: number, body: PartnerPriceRequestResponse) =>
  portalRequest<PartnerPriceRequestDetail>(`/partner/price-requests/${id}/respond`, { method: 'POST', body });

export type PartnerFinanceBalance = Schemas['PartnerFinanceBalance'];
export type PartnerFinanceScorecard = Schemas['PartnerFinanceScorecard'];
export type PartnerSettlementLine = Schemas['PartnerSettlementLine'];
export type PartnerFinanceSummary = Schemas['PartnerFinanceSummary'];

export const getPartnerFinanceSummary = () =>
  portalRequest<PartnerFinanceSummary>('/partner/finance');
