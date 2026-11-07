import { http, HttpResponse, type JsonBodyType } from 'msw';

import type { Schemas } from '@/api/portal';
import { businessToday } from '@/lib/format';
import { crmFormHandlers, resetMockCrmForm } from './crmForm';
import * as fixtures from './fixtures';
import * as partner from './partnerMock';

/**
 * Мок портального API на MSW — граница HTTP для dev (`VITE_PORTAL_MOCK=1`) и тестов.
 * Поведение — по `erp-portal.yaml`: без сессии 401, `can_act=false` → 403 на действиях,
 * чужое/несуществующее → 404, ошибки `{"detail": CODE}` (перечень `ErrorCode` контракта 0.3.0).
 *
 * Сценарии входа:
 * - `POST /auth/telegram` — любой `init_data`; содержит `bad` → 401, `viewer` → контакт без права действовать,
 *   `empty` → компания без объектов;
 * - `POST /auth/magic {token}` — токен короче 16 или длиннее 512 символов → 422; начинается с `expired` → 410,
 *   `forbidden` → 403 `FORBIDDEN` (компания в архиве), `throttled` → 429 `TOO_MANY_REQUESTS` с `Retry-After: 780`
 *   (`throttled-noheader` — без заголовка); `viewer` → без права действовать, `empty` → пустая компания, иное → основной контакт.
 *
 * Сценарии разделов: `POST /quotes/{id}/request-code` выдаёт код `MOCK_ACCEPT_CODE` (Telegram, если у контакта он есть,
 * иначе e-mail), без запроса или с другим кодом `accept` → 409 `QUOTE_CODE_INVALID`;
 * приёмка поставки — только из `delivered` (иначе 409 `DELIVERY_LINE_NOT_ACCEPTABLE`), замечание требует причину;
 * приёмка акта со сканом (`upload_id` из `/uploads`) кладёт скан в документы и в `scan_document_id`;
 * «Я оплатил» (`POST /invoices/{id}/proofs`) — платёжка `pending` в `proofs` счёта, оплаченный или отменённый счёт → 409
 * `INVOICE_NOT_OPEN`; комментарий к КП — только пока КП ждёт решения (иначе 409), пустой текст → 422 `TEXT_REQUIRED`;
 * КП с истёкшим сроком → 409 `QUOTE_EXPIRED`; повторное действие над закрытым объектом → 409 `*_FINALIZED`;
 * PDF документа `DOC_PREPARING_ONCE` первый раз отвечает 202 + `Retry-After`, `DOC_ALWAYS_PREPARING` — всегда 202.
 *
 * Telegram контакта (NOTIFY-1): по умолчанию не привязан и доступен; `POST /me/telegram-link` выдаёт ссылку на 15 минут;
 * в dev бот «привязывает» через три опроса `GET /me/telegram` после выпуска, в тестах — только `setMockTelegram`;
 * `DELETE /me/telegram` отвечает 202 с прежним `linked`, следующий опрос — уже `linked=false` (проекция пришла);
 * привязанному `POST /me/telegram-link` — 409 `TELEGRAM_ALREADY_LINKED`; `account` — имя привязанного аккаунта;
 * `POST /me/telegram/test` — 202, чаще раза в минуту — 429 с `Retry-After`, без привязки — 409 `TELEGRAM_NOT_LINKED`.
 * Чат кабинета (CHAT-1): лента компании `GET /messages[?after_id]`, `POST /messages` (повтор того же `client_message_id`
 * — прежнее сообщение, 200; текст `fail` — 503 для сценария «Не отправлено»), `POST /messages/read` — отметка не назад,
 * чужой `last_id` → 404; `/me.unread` — ответы менеджера после отметки. `pushManagerReply` — ответ менеджера для опроса.
 */
const API = '*/api/portal/v1';
const SESSION_KEY = 'cabinet.mock.session';

type Role = 'actor' | 'viewer';
type Dataset = 'demo' | 'empty';
/** Роли и модули сессии мока; модули — любые строки (тест «неизвестный модуль не рисуется»). */
export interface MockAccess {
  roles: Schemas['Me']['roles'];
  modules: string[];
}
interface MockSession {
  role: Role;
  auth_method: Schemas['Me']['auth_method'];
  /** `empty` — компания без запросов, КП, документов (пустые состояния экранов). */
  dataset?: Dataset;
  /** Роли и модули сессии (`/me`); нет — клиент со всеми разделами. Партнёр — `{roles: ['partner'], modules: [...]}`. */
  access?: MockAccess;
}

let memorySession: MockSession | null = null;

/** Сессия мока переживает перезагрузку вкладки (sessionStorage), как cookie настоящего ERP. */
function readSession(): MockSession | null {
  try {
    const raw = window.sessionStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as MockSession) : memorySession;
  } catch {
    return memorySession;
  }
}

export function setMockSession(session: MockSession | null): void {
  memorySession = session;
  try {
    if (session) window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else window.sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // Хранилище недоступно — сессия живёт до перезагрузки.
  }
}

function createDb(dataset: Dataset = 'demo') {
  const empty = dataset === 'empty';
  return {
    requests: empty ? [] : structuredClone(fixtures.requests),
    quotes: empty ? [] : structuredClone(fixtures.quotes),
    contracts: empty ? [] : structuredClone(fixtures.contracts),
    invoices: empty ? [] : structuredClone(fixtures.invoices),
    acts: empty ? [] : structuredClone(fixtures.acts),
    deliveries: empty ? [] : structuredClone(fixtures.deliveries),
    documents: empty ? [] : structuredClone(fixtures.documents),
    catalog: empty ? [] : structuredClone(fixtures.catalog),
    company: structuredClone(fixtures.company),
    team: empty ? [structuredClone(fixtures.contactActor)] : structuredClone(fixtures.team),
    sessions: structuredClone(fixtures.sessions),
    /** Сколько раз запрошен файл документа — для сценария «PDF готовится» (202 → 200). */
    fileRequests: new Map<number, number>(),
    /** КП, по которым клиент запросил код акцепта: id КП → выданный код. */
    quoteCodes: new Map<number, string>(),
    /** Загруженные файлы (`/uploads`): upload_id → имя; приёмка акта проверяет, что скан загружен. */
    uploads: new Map<string, string>(),
    telegram: fixtures.telegramMock(),
    /** Колокольчик (NOTIFY-2): лента контакта; у пустой компании — пусто (пустое состояние шторки). */
    notifications: empty ? [] : structuredClone(fixtures.notifications),
    notificationSettings: {
      telegram_connected: !empty,
      groups: {
        documents: { in_app: true, email: true, telegram: true, required: false },
        money: { in_app: true, email: true, telegram: true, required: false },
        deliveries: { in_app: true, email: false, telegram: true, required: false },
        messages: { in_app: true, email: true, telegram: true, required: false },
        partner_products: { in_app: true, email: true, telegram: true, required: false },
        security: { in_app: true, email: true, telegram: true, required: true },
      },
    } as Schemas['NotificationSettingsResponse'],
    /** Лента чата кабинета и отметка «прочитано» (одна на мок-сессию). */
    messages: empty ? [] : structuredClone(fixtures.messages),
    readMark: empty ? 0 : fixtures.MOCK_READ_MARK,
    /** «Мои товары» партнёра (PART-2): карточки с ценой компании и задачи загрузки прайса. */
    partnerProducts: empty ? [] : partner.partnerProducts(),
    priceTasks: new Map<string, ReturnType<typeof partner.newTask>>(),
    partnerApplication: null as Schemas['PartnerApplication'] | null,
  };
}

type Db = ReturnType<typeof createDb>;
let dbs: Record<Dataset, Db> = { demo: createDb('demo'), empty: createDb('empty') };

/** Для тестов: чистая сессия и данные фикстур. */
export function resetMockPortal(): void {
  setMockSession(null);
  dbs = { demo: createDb('demo'), empty: createDb('empty') };
  resetMockCrmForm();
}

/** Для тестов: состояние Telegram контакта в данных демо-компании (статус, доступность, авто-привязка). */
export function setMockTelegram(patch: Partial<fixtures.TelegramMock>): void {
  Object.assign(dbs.demo.telegram, patch);
}

/** Для тестов: заявка на партнерство для компании. */
export function setMockPartnerApplication(app: Schemas['PartnerApplication'] | null): void {
  dbs.demo.partnerApplication = app;
}

function contactFor(role: Role): Schemas['TeamMember'] {
  return role === 'viewer' ? fixtures.contactViewer : fixtures.contactActor;
}

/** `i***@example.com` — так ERP показывает, куда ушёл код. */
function maskEmail(email: string): string {
  const [name = '', domain = ''] = email.split('@');
  return `${name.slice(0, 1)}***@${domain}`;
}

function dbOf(session: MockSession): Db {
  return dbs[session.dataset ?? 'demo'];
}

function unreadOf(db: Db): number {
  return db.messages.filter((message) => message.direction === 'manager' && message.id > db.readMark).length;
}

function me(session: MockSession): Schemas['Me'] {
  const db = dbOf(session);
  return {
    ...fixtures.meFor(contactFor(session.role), session.auth_method, session.access, unreadOf(db)),
    company: db.company,
    notifications_unread: db.notifications.filter((item) => item.read_at === null).length,
  };
}

/** Тесты и dev: менеджер ответил в чат (следующий опрос `?after_id` его увидит). */
export function pushManagerReply(text: string, dataset: Dataset = 'demo'): Schemas['PortalMessage'] {
  const db = dbs[dataset];
  const message: Schemas['PortalMessage'] = {
    id: Math.max(500, ...db.messages.map((item) => item.id)) + 1,
    direction: 'manager',
    author_name: 'Илья Смирнов',
    mine: false,
    text,
    context: null,
    created_at: new Date().toISOString(),
    client_message_id: null,
    erased: false,
  };
  db.messages = [...db.messages, message];
  return message;
}

/** Стереть сообщение ленты по запросу автора (CHAT-1b: `crm.lead.erased` → ERP) — для сценария опроса в тестах и dev. */
export function eraseMessage(id: number, dataset: Dataset = 'demo'): void {
  const db = dbs[dataset];
  db.messages = db.messages.map((message) =>
    message.id === id ? { ...message, erased: true, text: '', author_name: null, context: null, mine: false } : message,
  );
}

const MESSAGES_PAGE = 50;
const CLIENT_MESSAGE_ID_RE = /^[A-Za-z0-9_-]{8,64}$/;

/** Номер документа для метки сообщения — только своего (чужой или несуществующий → `null`, ответ 404). */
function contextOf(db: Db, ref: Schemas['MessageContextRef']): Schemas['MessageContext'] | null {
  const find = (): string | undefined => {
    switch (ref.kind) {
      case 'quote':
        return db.quotes.find((item) => item.id === ref.id)?.number;
      case 'invoice':
        return db.invoices.find((item) => item.id === ref.id)?.number;
      case 'act':
        return db.acts.find((item) => item.id === ref.id)?.number;
      case 'deal':
        return fixtures.deals[ref.id]?.number;
    }
  };
  const number = find();
  return number ? { kind: ref.kind, id: ref.id, number } : null;
}

function sessionFromToken(token: string, authMethod: MockSession['auth_method']): MockSession {
  return {
    role: token.includes('viewer') ? 'viewer' : 'actor',
    auth_method: authMethod,
    dataset: token.includes('empty') ? 'empty' : 'demo',
    // Токен с `dual` — клиент и партнёр сразу (меню «Покупаю / Поставляю»), `partner` — партнёр (каталог и заявки +
    // «Мои товары»), `partner-min` — только «Мои товары» (ADR-0022)
    access: token.includes('dual')
      ? { roles: ['client', 'partner'], modules: [...fixtures.CLIENT_ACCESS.modules, 'my_products'] }
      : token.includes('partner-min')
        ? { roles: ['partner'], modules: ['my_products', 'messages', 'profile'] }
        : token.includes('partner')
          ? { roles: ['partner'], modules: ['my_products', 'catalog_requests', 'messages', 'profile'] }
          : undefined,
  };
}

function error(status: number, detail: string) {
  return HttpResponse.json({ detail } satisfies Schemas['Error'], { status });
}

function json<T extends JsonBodyType>(body: T, status = 200) {
  return HttpResponse.json(body, { status });
}

/** Обёртка эндпоинта с сессией: без неё 401, для действий без `can_act` — 403. */
function withSession<P>(
  resolver: (args: { session: MockSession; db: Db; params: P; request: Request }) => Response | Promise<Response>,
  { action = false }: { action?: boolean } = {},
) {
  return ({ params, request }: { params: P; request: Request }) => {
    const session = readSession();
    if (!session) return error(401, 'UNAUTHORIZED');
    if (action && !contactFor(session.role).can_act) return error(403, 'FORBIDDEN');
    return resolver({ session, db: dbOf(session), params, request });
  };
}

type IdParams = { id: string };

function byId<T extends { id: number }>(items: T[], id: string): T | undefined {
  return items.find((item) => String(item.id) === id);
}

/** Карточка в списке каталога — без документов (они только в детальной карточке). */
function listItem(item: Schemas['CatalogItem']): Schemas['CatalogItem'] {
  const copy = { ...item };
  delete copy.documents;
  return copy;
}

/** Элемент списка КП — карточка без строк и служебных полей (`deal` остаётся как есть). */
function quoteListItem(quote: Schemas['Quote']): Schemas['QuoteListItem'] {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { lines, public_url, pdf_document_id, rejected_reason, comments, ...item } = quote;
  return item;
}

async function readJson<T>(request: Request): Promise<Partial<T>> {
  try {
    return ((await request.json()) ?? {}) as Partial<T>;
  } catch {
    return {};
  }
}

const MAGIC_TOKEN_MIN = 16;
const MAGIC_TOKEN_MAX = 512;
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const QUANTITY_RE = /^\d+(\.\d+)?$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function validRequestBody(body: Partial<Schemas['ClientRequestCreate']>): body is Schemas['ClientRequestCreate'] {
  if (!body.summary?.trim() || body.summary.length > 5000) return false;
  // `lines` необязателен (контракт 0.3.0): запрос может быть одним описанием.
  if (body.lines === undefined) return true;
  if (!Array.isArray(body.lines)) return false;
  return body.lines.every(
    (line) =>
      typeof line.text === 'string' &&
      line.text.trim().length > 0 &&
      line.text.length <= 1000 &&
      (line.quantity === undefined || line.quantity === null || QUANTITY_RE.test(line.quantity)),
  );
}

export const handlers = [
  // --- auth -----------------------------------------------------------------------------
  http.post(`${API}/auth/telegram`, async ({ request }) => {
    const body = await readJson<{ init_data: string }>(request);
    const initData = body.init_data ?? '';
    if (!initData || initData.includes('bad')) return error(401, 'INVALID_INIT_DATA');
    const session = sessionFromToken(initData, 'telegram');
    setMockSession(session);
    return json(me(session));
  }),
  http.post(`${API}/auth/magic-link`, async ({ request }) => {
    const body = await readJson<{ email: string }>(request);
    if (!body.email || !body.email.includes('@')) return error(422, 'VALIDATION_ERROR');
    if (body.email.startsWith('throttled')) {
      return HttpResponse.json({ detail: 'TOO_MANY_REQUESTS' }, { status: 429, headers: { 'Retry-After': '45' } });
    }
    if (body.email.startsWith('unknown') || body.email.startsWith('unregistered')) {
      return json({ status: 'not_registered', sent: false, email: body.email });
    }
    return json({ status: 'ok', sent: true, email: body.email });
  }),
  http.get(`${API}/countries`, () => {
    return json([
      { code: 'UZ', name: 'Узбекистан', phone_code: '+998', phone_mask: '+998 (99) 999-99-99', phone_placeholder: '+998 90 123-45-67', tax_label: 'ИНН (STIR)', tax_placeholder: '123456789', is_uzbekistan: true },
      { code: 'KZ', name: 'Казахстан', phone_code: '+7', phone_mask: '+7 (799) 999-99-99', phone_placeholder: '+7 701 123-45-67', tax_label: 'БИН / ИИН', tax_placeholder: '123456789012', is_uzbekistan: false },
      { code: 'RU', name: 'Россия', phone_code: '+7', phone_mask: '+7 (999) 999-99-99', phone_placeholder: '+7 916 123-45-67', tax_label: 'ИНН', tax_placeholder: '1234567890', is_uzbekistan: false },
      { code: 'CN', name: 'Китай', phone_code: '+86', phone_mask: '+86 999 9999 9999', phone_placeholder: '+86 138 1234 5678', tax_label: 'USCC', tax_placeholder: '91110000000000000X', is_uzbekistan: false },
      { code: 'TR', name: 'Турция', phone_code: '+90', phone_mask: '+90 999 999 99 99', phone_placeholder: '+90 532 123 45 67', tax_label: 'VKN', tax_placeholder: '1234567890', is_uzbekistan: false },
    ]);
  }),
  http.post(`${API}/auth/magic`, async ({ request }) => {
    const { token } = await readJson<{ token: string }>(request);
    // Контракт 0.3.0: токен — 16…512 символов, иначе 422.
    if (typeof token !== 'string' || token.length < MAGIC_TOKEN_MIN || token.length > MAGIC_TOKEN_MAX) {
      return error(422, 'VALIDATION_ERROR');
    }
    if (token.startsWith('expired')) return error(410, 'MAGIC_LINK_EXPIRED');
    if (token.startsWith('forbidden')) return error(403, 'FORBIDDEN');
    if (token.startsWith('throttled-noheader')) return error(429, 'TOO_MANY_REQUESTS');
    if (token.startsWith('throttled')) {
      return HttpResponse.json({ detail: 'TOO_MANY_REQUESTS' }, { status: 429, headers: { 'Retry-After': '780' } });
    }
    const session = sessionFromToken(token, 'magic_link');
    setMockSession(session);
    return json(me(session));
  }),
  // B-MAIL-1: код из письма. Мок: `000000` — неверный, `111111` — пять неверных подряд (блок), остальные 6 цифр — вход.
  http.post(`${API}/auth/code`, async ({ request }) => {
    const body = await readJson<{ email?: string; code?: string }>(request);
    if (!body.email?.includes('@') || !/^\d{6}$/.test(body.code ?? '')) return error(422, 'VALIDATION_ERROR');
    if (body.code === '000000') return error(422, 'LOGIN_CODE_INVALID');
    if (body.code === '111111') return error(429, 'LOGIN_CODE_LOCKED');
    const session = sessionFromToken(body.email, 'magic_link');
    setMockSession(session);
    return json(me(session));
  }),
  // PART-ONBOARD-1: публичная заявка кандидата в партнёры
  http.post(`${API}/auth/partner-application`, async ({ request }) => {
    const body = await readJson<Schemas['PartnerApplicationPublicCreate']>(request);
    if (body.website) return error(400, 'HONEYPOT_DETECTED');
    if (!body.consent) return error(400, 'CONSENT_REQUIRED');
    if (!body.company_name?.trim() || !body.email?.trim() || !body.categories_description?.trim()) {
      return error(422, 'VALIDATION_ERROR');
    }
    return json({ id: 101, status: 'submitted' } satisfies Schemas['PartnerApplicationPublicResult'], 201);
  }),
  http.post(
    `${API}/auth/logout`,
    withSession(() => {
      setMockSession(null);
      return new HttpResponse(null, { status: 204 });
    }),
  ),
  http.get(
    `${API}/auth/sessions`,
    withSession(({ db }) => json(db.sessions)),
  ),
  http.post(
    `${API}/auth/sessions/revoke-others`,
    withSession(({ db }) => {
      const revokedCount = db.sessions.filter((s) => !s.is_current).length;
      db.sessions = db.sessions.filter((s) => s.is_current);
      return json({ revoked_count: revokedCount });
    }),
  ),
  http.get(`${API}/me`, withSession(({ session }) => json(me(session)))),
  http.get(
    `${API}/me/telegram`,
    withSession(({ db }) => {
      const tg = db.telegram;
      if (tg.unlinkPending) {
        tg.linked = false;
        tg.unlinkPending = false;
      } else if (tg.pollsUntilLinked !== null && --tg.pollsUntilLinked <= 0) {
        tg.linked = true;
        tg.pollsUntilLinked = null;
      }
      return json(fixtures.telegramStatus(tg));
    }),
  ),
  // Право «действовать» не нужно: привязка Telegram — настройка самого контакта.
  http.post(
    `${API}/me/telegram-link`,
    withSession(({ db }) => {
      const tg = db.telegram;
      if (tg.linked) return error(409, 'TELEGRAM_ALREADY_LINKED');
      if (tg.linkError) return error(tg.linkError === 'CONTACT_NOT_IN_CRM' ? 422 : 503, tg.linkError);
      tg.pollsUntilLinked = tg.autoLinkAfterPolls;
      return json(fixtures.telegramLink(new Date()), 201);
    }),
  ),
  http.post(
    `${API}/me/telegram/test`,
    withSession(({ db }) => {
      const tg = db.telegram;
      if (!tg.linked) return error(409, 'TELEGRAM_NOT_LINKED');
      const now = Date.now();
      const waitMs = tg.lastTestAt === null ? 0 : tg.lastTestAt + fixtures.TELEGRAM_TEST_INTERVAL_S * 1000 - now;
      if (waitMs > 0) {
        return HttpResponse.json({ detail: 'TOO_MANY_REQUESTS' } satisfies Schemas['Error'], {
          status: 429,
          headers: { 'Retry-After': String(Math.ceil(waitMs / 1000)) },
        });
      }
      tg.lastTestAt = now;
      tg.testsSent += 1;
      return json(fixtures.telegramStatus(tg), 202);
    }),
  ),
  http.delete(
    `${API}/me/telegram`,
    withSession(({ db }) => {
      const tg = db.telegram;
      if (tg.linked) tg.unlinkPending = true;
      return json(fixtures.telegramStatus(tg), 202);
    }),
  ),

  // --- колокольчик (NOTIFY-2): по убыванию id, `before_id` + `limit`; «прочитано» — свои id или все ------------
  http.get(
    `${API}/notifications`,
    withSession(({ db, request }) => {
      const url = new URL(request.url);
      const limit = Number(url.searchParams.get('limit') ?? 20);
      const before = Number(url.searchParams.get('before_id') ?? 0);
      if (!Number.isInteger(limit) || limit < 1 || limit > 50) return error(422, 'VALIDATION_ERROR');
      const rest = db.notifications.filter((item) => !before || item.id < before).sort((a, b) => b.id - a.id);
      return json({ items: rest.slice(0, limit), has_more: rest.length > limit } satisfies Schemas['NotificationPage']);
    }),
  ),
  http.post(
    `${API}/notifications/read`,
    withSession(async ({ db, request }) => {
      const body = await readJson<Schemas['NotificationReadMark']>(request);
      const all = body.all === true;
      if (all === Array.isArray(body.ids)) return error(422, 'VALIDATION_ERROR');
      const ids = new Set(body.ids ?? []);
      const now = new Date().toISOString();
      for (const item of db.notifications) {
        if (item.read_at === null && (all || ids.has(item.id))) item.read_at = now;
      }
      const unread = db.notifications.filter((item) => item.read_at === null).length;
      return json({ unread } satisfies Schemas['NotificationUnread']);
    }),
  ),
  http.get(
    `${API}/notifications/settings`,
    withSession(({ db }) => {
      return json({
        telegram_connected: db.telegram.linked,
        groups: db.notificationSettings.groups,
      } satisfies Schemas['NotificationSettingsResponse']);
    }),
  ),
  http.patch(
    `${API}/notifications/settings`,
    withSession(async ({ db, request }) => {
      const body = await readJson<Schemas['NotificationSettingsUpdate']>(request);
      if (!body.groups) return error(422, 'VALIDATION_ERROR');
      for (const [group, updates] of Object.entries(body.groups)) {
        if (group === 'security') continue;
        if (db.notificationSettings.groups[group as keyof Schemas['NotificationGroupSettingsMap']]) {
          const target = db.notificationSettings.groups[group as keyof Schemas['NotificationGroupSettingsMap']];
          if (updates.email !== undefined) target.email = updates.email;
          if (updates.telegram !== undefined) target.telegram = updates.telegram;
        }
      }
      return json({
        telegram_connected: db.telegram.linked,
        groups: db.notificationSettings.groups,
      } satisfies Schemas['NotificationSettingsResponse']);
    }),
  ),

  // --- запросы ------------------------------------------------------------------------------
  http.get(
    `${API}/requests`,
    withSession(({ db, request }) => {
      const url = new URL(request.url);
      const q = (url.searchParams.get('q') || '').trim().toLowerCase();
      const status = url.searchParams.get('status');
      let list = db.requests;
      if (status) {
        list = list.filter((r) => r.status === status);
      }
      if (q) {
        list = list.filter(
          (r) =>
            r.number.toLowerCase().includes(q) ||
            r.summary.toLowerCase().includes(q) ||
            (r.lines && r.lines.some((l) => l.text.toLowerCase().includes(q))),
        );
      }
      return json(list);
    }),
  ),
  http.get<IdParams>(
    `${API}/requests/:id`,
    withSession<IdParams>(({ db, params }) => {
      const item = byId(db.requests, params.id);
      return item ? json(item) : error(404, 'NOT_FOUND');
    }),
  ),
  http.post<IdParams>(
    `${API}/requests/:id/reorder`,
    withSession<IdParams>(
      ({ db, params }) => {
        const item = byId(db.requests, params.id);
        if (!item) return error(404, 'NOT_FOUND');
        const nextId = Math.max(500, ...db.requests.map((r) => r.id)) + 1;
        const created: Schemas['ClientRequest'] = {
          id: nextId,
          number: `Z-2026-${String(nextId - 400).padStart(4, '0')}`,
          status: 'new',
          outcome: null,
          summary: `Повтор запроса ${item.number}: ${item.summary}`,
          source: 'cabinet',
          deal: null,
          created_at: new Date().toISOString(),
          lines: item.lines ?? [],
          attachments: [],
        };
        db.requests = [created, ...db.requests];
        return json(created, 201);
      },
      { action: true },
    ),
  ),
  http.post(
    `${API}/requests`,
    withSession(
      async ({ db, request }) => {
        const body = await readJson<Schemas['ClientRequestCreate']>(request);
        if (!validRequestBody(body)) return error(422, 'VALIDATION_ERROR');
        const nextId = Math.max(500, ...db.requests.map((item) => item.id)) + 1;
        const created: Schemas['ClientRequest'] = {
          id: nextId,
          number: `Z-2026-${String(nextId - 400).padStart(4, '0')}`,
          status: 'new',
          outcome: null,
          summary: body.summary,
          source: 'cabinet',
          deal: null,
          created_at: new Date().toISOString(),
          lines: body.lines ?? [],
          attachments: body.attachments ?? [],
        };
        db.requests = [created, ...db.requests];
        return json(created, 201);
      },
      { action: true },
    ),
  ),

  // --- КП -------------------------------------------------------------------------------------
  http.get(`${API}/quotes`, withSession(({ db }) => json(db.quotes.map(quoteListItem)))),
  http.get<IdParams>(
    `${API}/quotes/:id`,
    withSession<IdParams>(({ db, params }) => {
      const quote = byId(db.quotes, params.id);
      return quote ? json(quote) : error(404, 'NOT_FOUND');
    }),
  ),
  http.post<IdParams>(
    `${API}/quotes/:id/request-code`,
    withSession<IdParams>(
      ({ session, db, params }) => {
        const quote = byId(db.quotes, params.id);
        if (!quote) return error(404, 'NOT_FOUND');
        if (quote.status !== 'sent' && quote.status !== 'viewed') return error(409, 'QUOTE_FINALIZED');
        if (quote.valid_until && quote.valid_until < businessToday()) return error(409, 'QUOTE_EXPIRED');
        const contact = contactFor(session.role);
        const viaTelegram = contact.has_telegram && contact.preferred_channel !== 'email';
        if (!viaTelegram && !contact.email) return error(422, 'CONTACT_CHANNEL_REQUIRED');
        db.quoteCodes.set(quote.id, fixtures.MOCK_ACCEPT_CODE);
        const sent: Schemas['AcceptanceCodeSent'] = viaTelegram
          ? { channel: 'telegram', sent_to: 'Telegram', expires_in: 900 }
          : { channel: 'email', sent_to: maskEmail(contact.email ?? ''), expires_in: 900 };
        return json(sent, 202);
      },
      { action: true },
    ),
  ),
  http.post<IdParams>(
    `${API}/quotes/:id/accept`,
    withSession<IdParams>(
      async ({ db, params, request }) => {
        const quote = byId(db.quotes, params.id);
        if (!quote) return error(404, 'NOT_FOUND');
        const { code } = await readJson<{ code: string }>(request);
        if (quote.status !== 'sent' && quote.status !== 'viewed') return error(409, 'QUOTE_FINALIZED');
        if (quote.valid_until && quote.valid_until < businessToday()) return error(409, 'QUOTE_EXPIRED');
        if (!code || code.length < 4 || code.length > 12) return error(422, 'VALIDATION_ERROR');
        if (code !== db.quoteCodes.get(quote.id)) return error(409, 'QUOTE_CODE_INVALID');
        db.quoteCodes.delete(quote.id);
        quote.status = 'accepted';
        // ERP создаёт договор сам (BUSINESS §4, шаг 6) — без файла, пока PDF не отрендерен.
        if (!db.contracts.some((item) => item.deal.id === quote.deal.id)) {
          db.contracts = [
            {
              id: 400 + quote.deal.id,
              ...fixtures.dealOf(quote.deal.id),
              number: `D-2026-${String(quote.deal.id).padStart(4, '0')}`,
              status: 'sent',
              signed_by_client_at: null,
              signed_by_company_at: null,
              document_id: null,
            },
            ...db.contracts,
          ];
        }
        return json(quote);
      },
      { action: true },
    ),
  ),
  http.post<IdParams>(
    `${API}/quotes/:id/reject`,
    withSession<IdParams>(
      async ({ db, params, request }) => {
        const quote = byId(db.quotes, params.id);
        if (!quote) return error(404, 'NOT_FOUND');
        if (quote.status !== 'sent' && quote.status !== 'viewed') return error(409, 'QUOTE_FINALIZED');
        const { reason } = await readJson<Schemas['Reason']>(request);
        if (!reason?.trim()) return error(422, 'REASON_REQUIRED');
        quote.status = 'rejected';
        quote.rejected_reason = reason;
        return json(quote);
      },
      { action: true },
    ),
  ),

  http.post<IdParams>(
    `${API}/quotes/:id/comments`,
    withSession<IdParams>(
      async ({ db, params, request, session }) => {
        const quote = byId(db.quotes, params.id);
        if (!quote) return error(404, 'NOT_FOUND');
        if (quote.status !== 'sent' && quote.status !== 'viewed') return error(409, 'QUOTE_FINALIZED');
        if (quote.valid_until && quote.valid_until < businessToday()) return error(409, 'QUOTE_EXPIRED');
        const { text } = await readJson<Schemas['QuoteCommentCreate']>(request);
        if (typeof text !== 'string' || text.length > 2000) return error(422, 'VALIDATION_ERROR');
        if (!text.trim()) return error(422, 'TEXT_REQUIRED');
        const comment: Schemas['QuoteComment'] = {
          id: Math.max(0, ...quote.comments.map((item) => item.id)) + 1,
          author: 'client',
          author_name: contactFor(session.role).name,
          text: text.trim(),
          created_at: new Date().toISOString(),
        };
        quote.comments = [...quote.comments, comment];
        return json(comment, 201);
      },
      { action: true },
    ),
  ),

  // --- договоры, счета, акты ------------------------------------------------------------------
  http.get(`${API}/contracts`, withSession(({ db }) => json(db.contracts))),
  http.post<IdParams>(
    `${API}/contracts/:id/sign`,
    withSession<IdParams>(
      ({ db, params }) => {
        const contract = byId(db.contracts, params.id);
        if (!contract) return error(404, 'NOT_FOUND');
        if (contract.status !== 'sent' && contract.status !== 'signed_by_company') return error(409, 'CONTRACT_FINALIZED');
        // D2-5: согласие клиента не подписывает договор: «Подписан» ставит скан у сотрудника, клиенту — «Вы согласовали, ждём подписания».
        contract.status = 'signed_by_client';
        contract.signed_by_client_at = new Date().toISOString();
        return json(contract);
      },
      { action: true },
    ),
  ),
  http.get(`${API}/invoices`, withSession(({ db }) => json(db.invoices))),
  http.post<IdParams>(
    `${API}/invoices/:id/proofs`,
    withSession<IdParams>(
      async ({ db, params, request }) => {
        const invoice = byId(db.invoices, params.id);
        if (!invoice) return error(404, 'NOT_FOUND');
        if (invoice.status === 'paid' || invoice.status === 'cancelled') return error(409, 'INVOICE_NOT_OPEN');
        const body = await readJson<Schemas['PaymentProofCreate']>(request);
        const name = body.upload_id === undefined ? undefined : db.uploads.get(body.upload_id);
        if (name === undefined) return error(422, 'UPLOAD_NOT_FOUND');
        if (body.amount !== undefined && body.amount !== null && !/^\d+\.\d{2}$/.test(body.amount)) return error(422, 'VALIDATION_ERROR');
        if (body.paid_on && body.paid_on > businessToday()) return error(422, 'VALIDATION_ERROR');
        if (body.comment && body.comment.length > 500) return error(422, 'VALIDATION_ERROR');
        const proof: Schemas['PaymentProof'] = {
          id: Math.max(100, ...db.invoices.flatMap((item) => item.proofs.map((p) => p.id))) + 1,
          status: 'pending',
          source: 'cabinet',
          file_name: name,
          submitted_at: new Date().toISOString(),
          paid_on: body.paid_on ?? null,
          amount: body.amount ? { amount: body.amount, currency: invoice.total.currency } : null,
          comment: body.comment ?? null,
          confirmed_at: null,
          reject_reason: null,
        };
        invoice.proofs = [...invoice.proofs, proof];
        return json(proof, 201);
      },
      { action: true },
    ),
  ),
  http.get(`${API}/acts`, withSession(({ db }) => json(db.acts))),
  http.post<IdParams>(
    `${API}/acts/:id/accept`,
    withSession<IdParams>(
      async ({ db, params, request }) => {
        const act = byId(db.acts, params.id);
        if (!act) return error(404, 'NOT_FOUND');
        if (act.status !== 'issued') return error(409, 'ACT_FINALIZED');
        const { upload_id } = await readJson<Schemas['ActAccept']>(request);
        if (upload_id !== undefined) {
          const name = db.uploads.get(upload_id);
          if (name === undefined) return error(422, 'UPLOAD_NOT_FOUND');
          // Скан подписанного экземпляра ERP сохраняет документом сделки и привязывает к акту.
          const scan: Schemas['Document'] = {
            id: 800 + act.id,
            deal: act.deal ?? null,
            kind: 'act',
            number: act.number,
            date: businessToday(),
            title: `Скан акта № ${act.number}`,
            file_name: name,
          };
          db.documents = [scan, ...db.documents.filter((doc) => doc.id !== scan.id)];
          act.scan_document_id = scan.id;
        }
        act.status = 'accepted';
        return json(act);
      },
      { action: true },
    ),
  ),
  http.post<IdParams>(
    `${API}/acts/:id/return`,
    withSession<IdParams>(
      async ({ db, params, request }) => {
        const act = byId(db.acts, params.id);
        if (!act) return error(404, 'NOT_FOUND');
        if (act.status !== 'issued') return error(409, 'ACT_FINALIZED');
        const { reason } = await readJson<Schemas['Reason']>(request);
        if (!reason?.trim()) return error(422, 'REASON_REQUIRED');
        act.status = 'returned';
        act.returned_reason = reason;
        return json(act);
      },
      { action: true },
    ),
  ),

  // --- поставки и документы -------------------------------------------------------------------
  http.get(`${API}/deliveries`, withSession(({ db }) => json(db.deliveries))),
  http.post<IdParams>(
    `${API}/deliveries/:id/accept`,
    withSession<IdParams>(
      ({ db, params }) => {
        const line = byId(db.deliveries, params.id);
        if (!line) return error(404, 'NOT_FOUND');
        if (line.status !== 'delivered') return error(409, 'DELIVERY_LINE_NOT_ACCEPTABLE');
        line.status = 'accepted';
        line.accepted_at = new Date().toISOString();
        line.remark = null;
        return json(line);
      },
      { action: true },
    ),
  ),
  http.post<IdParams>(
    `${API}/deliveries/:id/dispute`,
    withSession<IdParams>(
      async ({ db, params, request }) => {
        const line = byId(db.deliveries, params.id);
        if (!line) return error(404, 'NOT_FOUND');
        if (line.status !== 'delivered') return error(409, 'DELIVERY_LINE_NOT_ACCEPTABLE');
        const { reason } = await readJson<Schemas['Reason']>(request);
        if (!reason?.trim()) return error(422, 'REASON_REQUIRED');
        line.status = 'disputed';
        line.accepted_at = new Date().toISOString();
        line.remark = reason;
        return json(line);
      },
      { action: true },
    ),
  ),
  http.get(
    `${API}/documents`,
    withSession(({ db, request }) => {
      const url = new URL(request.url);
      const kind = url.searchParams.get('kind');
      const dealId = url.searchParams.get('deal_id');
      const q = (url.searchParams.get('q') || '').trim().toLowerCase();
      const dateFrom = url.searchParams.get('date_from');
      const dateTo = url.searchParams.get('date_to');
      let list = db.documents.filter(
        (doc) => (!kind || doc.kind === kind) && (!dealId || String(doc.deal?.id) === dealId),
      );
      if (dateFrom) list = list.filter((doc) => doc.date >= dateFrom);
      if (dateTo) list = list.filter((doc) => doc.date <= dateTo);
      if (q) {
        list = list.filter(
          (doc) =>
            doc.title.toLowerCase().includes(q) ||
            doc.number.toLowerCase().includes(q) ||
            (doc.deal && doc.deal.number.toLowerCase().includes(q)),
        );
      }
      return json(list);
    }),
  ),
  http.get<IdParams>(
    `${API}/documents/:id/file`,
    withSession<IdParams>(({ db, params }) => {
      const doc = byId(db.documents, params.id);
      if (!doc) return error(404, 'NOT_FOUND');
      const seen = (db.fileRequests.get(doc.id) ?? 0) + 1;
      db.fileRequests.set(doc.id, seen);
      if (doc.id === fixtures.DOC_ALWAYS_PREPARING || (doc.id === fixtures.DOC_PREPARING_ONCE && seen === 1)) {
        return new HttpResponse(null, { status: 202, headers: { 'Retry-After': '1' } });
      }
      const fileName = doc.file_name ?? `${doc.number}.pdf`;
      return new HttpResponse('%PDF-1.4\n% mock\n', {
        headers: {
          'Content-Type': 'application/pdf',
          'Content-Disposition': `attachment; filename="${fileName}"; filename*=UTF-8''${encodeURIComponent(fileName)}`,
        },
      });
    }),
  ),

  // --- загрузка файлов (Q-14) -----------------------------------------------------------------
  http.post(
    `${API}/uploads`,
    withSession(
      async ({ db, request }) => {
        const formData = await request.formData();
        const file = formData.get('file');
        if (!file || typeof file === 'string') return error(400, 'FILE_REQUIRED');
        if (file.size > MAX_UPLOAD_BYTES) return error(422, 'FILE_TOO_LARGE');
        const name = file.name || 'document.pdf';
        const uploadId = `upl_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
        db.uploads.set(uploadId, name);
        const res: Schemas['PortalUploadResponse'] = {
          upload_id: uploadId,
          name,
          size_bytes: file.size,
          mime_type: file.type || 'application/octet-stream',
        };
        return json(res, 201);
      },
      { action: true },
    ),
  ),

  // --- каталог ----------------------------------------------------------------------------------
  http.get(
    `${API}/catalog/categories`,
    withSession(({ db }) => {
      const counts = new Map<string, number>();
      for (const item of db.catalog) {
        if (item.category) counts.set(item.category, (counts.get(item.category) ?? 0) + 1);
      }
      let catId = 1;
      const categories: Schemas['CatalogCategory'][] = Array.from(counts.entries()).map(([name, count]) => ({
        id: catId++,
        name,
        count,
      }));
      return json(categories);
    }),
  ),
  http.get(
    `${API}/catalog`,
    withSession(({ db, request }) => {
      const url = new URL(request.url);
      const q = url.searchParams.get('q')?.trim().toLowerCase() ?? '';
      const page = Math.max(1, Number(url.searchParams.get('page') ?? 1) || 1);
      const pageSize = Math.min(100, Math.max(1, Number(url.searchParams.get('page_size') ?? 20) || 20));
      const found = db.catalog.filter(
        (item) =>
          !q ||
          item.name.toLowerCase().includes(q) ||
          (item.description ?? '').toLowerCase().includes(q) ||
          (item.category ?? '').toLowerCase().includes(q),
      );
      const body: Schemas['CatalogPage'] = {
        // Как ERP: документы карточки — только в детальной карточке, в списке их нет.
        items: found.slice((page - 1) * pageSize, page * pageSize).map(listItem),
        page,
        page_size: pageSize,
        total: found.length,
      };
      return json(body);
    }),
  ),
  http.get<IdParams>(
    `${API}/catalog/:id`,
    withSession<IdParams>(({ db, params }) => {
      const item = byId(db.catalog, params.id);
      return item ? json(item) : error(404, 'NOT_FOUND');
    }),
  ),
  http.get<IdParams & { docId: string }>(
    `${API}/catalog/:id/documents/:docId/file`,
    withSession<IdParams & { docId: string }>(({ db, params }) => {
      const item = byId(db.catalog, params.id);
      const doc = item?.documents?.find((d) => d.id === Number(params.docId));
      if (!doc) return error(404, 'NOT_FOUND');
      // Как ERP: имя файла — из названия документа, не из загруженного файла.
      const fileName = `${doc.title.replace(/[^\p{L}\p{N}._-]+/gu, '_')}.pdf`;
      return new HttpResponse('%PDF-1.4\n% mock\n', {
        headers: {
          'Content-Type': 'application/pdf',
          'Content-Disposition': `attachment; filename="document.pdf"; filename*=UTF-8''${encodeURIComponent(fileName)}`,
        },
      });
    }),
  ),

  // --- компания и команда -----------------------------------------------------------------------
  http.get(`${API}/company`, withSession(({ db }) => json(db.company))),
  http.get(
    `${API}/company/security-log`,
    withSession(({ session }) => {
      const currentContact = contactFor(session.role);
      if (!currentContact.is_admin) return error(403, 'ADMIN_REQUIRED');
      return json({
        items: [
          {
            id: 'sec-1',
            event_type: 'login',
            created_at: new Date(Date.now() - 3600_000).toISOString(),
            actor_name: currentContact.name,
            actor_email: currentContact.email,
            ip_address: '192.168.1.10',
            user_agent: 'Mozilla/5.0 Chrome/120',
            target_name: null,
            details: 'Вход в систему',
          },
        ],
      });
    }),
  ),
  http.put(
    `${API}/company`,
    withSession(
      async ({ db, session, request }) => {
        const body = await readJson<Schemas['CompanyUpdate']>(request);
        if (body.name !== undefined && !body.name.trim()) return error(422, 'VALIDATION_ERROR');
        if (body.inn !== undefined && body.inn !== '' && !/^\d{9,14}$/.test(body.inn)) return error(422, 'INN_INVALID');
        if (body.bank_details !== undefined && body.bank_details !== (db.company.bank_details ?? '')) {
          const currentContact = contactFor(session.role);
          if (!currentContact.is_admin) return error(409, 'ADMIN_REQUIRED');
          const noticeId = (db.notifications[0]?.id ?? 0) + 1;
          db.notifications.unshift({
            id: noticeId,
            kind: 'bank_requisites_changed',
            group: 'security',
            object: { type: 'chat', id: 0, number: null },
            action: 'status_changed',
            text_key: 'security_bank_requisites_changed',
            params: { actor: currentContact.name || currentContact.email || 'Admin' },
            link: '/company',
            created_at: new Date().toISOString(),
            read_at: null,
          });
        }
        const country = body.country_code
          ? { code: body.country_code, name: body.country_code === 'UZ' ? 'Узбекистан' : 'Казахстан' }
          : db.company.country;
        db.company = { ...db.company, ...body, country };
        return json(db.company);
      },
      { action: true },
    ),
  ),
  http.get(
    `${API}/company/partner-application`,
    withSession(({ db, session }) => {
      const alreadyPartner = session.access?.roles.includes('partner') ?? false;
      const app = db.partnerApplication;
      return json({
        already_partner: alreadyPartner,
        has_application:
          app !== null &&
          (app.status === 'submitted' || app.status === 'contract_sent' || app.status === 'candidate_agreed'),
        application: app,
      } satisfies Schemas['PartnerApplicationStatusResponse']);
    }),
  ),
  http.get(
    `${API}/company/partner-application/contract-pdf`,
    withSession(() => {
      return new HttpResponse(new Uint8Array([37, 80, 68, 70]), {
        headers: {
          'Content-Type': 'application/pdf',
          'Content-Disposition': 'inline; filename="Partner_Contract.pdf"',
        },
      });
    }),
  ),
  http.post(
    `${API}/company/partner-application/agree`,
    withSession(
      async ({ db, request }) => {
        if (!db.partnerApplication || db.partnerApplication.status !== 'contract_sent') {
          return error(400, 'NOT_IN_CONTRACT_SENT_STATUS');
        }
        const body = ((await readJson<{ notes?: string }>(request).catch(() => ({}))) || {}) as { notes?: string };
        db.partnerApplication.status = 'candidate_agreed';
        db.partnerApplication.candidate_agreed_at = new Date().toISOString();
        if (body.notes) {
          db.partnerApplication.candidate_notes = body.notes;
        }
        return json(db.partnerApplication);
      },
      { action: true },
    ),
  ),
  http.post(
    `${API}/company/partner-application`,
    withSession(
      async ({ db, session, request }) => {
        const alreadyPartner = session.access?.roles.includes('partner') ?? false;
        if (alreadyPartner) return error(409, 'ALREADY_PARTNER');
        if (
          db.partnerApplication &&
          (db.partnerApplication.status === 'submitted' || db.partnerApplication.status === 'contract_sent')
        ) {
          return error(409, 'APPLICATION_EXISTS');
        }
        const body = await readJson<Schemas['PartnerApplicationClientCreate']>(request);
        if (!body.categories_description || body.categories_description.trim().length < 5) {
          return error(422, 'VALIDATION_ERROR');
        }
        const created: Schemas['PartnerApplication'] = {
          id: 102,
          status: 'submitted',
          kind: body.kind ?? 'supplier',
          categories_description: body.categories_description.trim(),
          company_name: db.company.name,
          inn: db.company.inn ?? null,
          contact_name: fixtures.contactActor.name,
          email: fixtures.contactActor.email ?? '',
          phone: fixtures.contactActor.phone ?? null,
          contract_number: null,
          contract_date: null,
          rejected_reason: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };
        db.partnerApplication = created;
        return json(created, 201);
      },
      { action: true },
    ),
  ),
  // --- чат кабинета (CHAT-1) ----------------------------------------------------------------
  http.get(
    `${API}/messages`,
    withSession(({ db, request }) => {
      const url = new URL(request.url);
      const after = Number(url.searchParams.get('after_id') ?? '');
      const limit = Math.min(100, Math.max(1, Number(url.searchParams.get('limit') ?? MESSAGES_PAGE) || MESSAGES_PAGE));
      if (url.searchParams.has('after_id')) {
        const newer = db.messages.filter((message) => message.id > after);
        const erased_ids = db.messages.filter((message) => message.erased && message.id <= after).map((message) => message.id);
        return json({ items: newer.slice(0, limit), has_more: newer.length > limit, erased_ids } satisfies Schemas['PortalMessagePage']);
      }
      const items = db.messages.slice(-limit);
      return json({ items, has_more: db.messages.length > limit, erased_ids: [] } satisfies Schemas['PortalMessagePage']);
    }),
  ),
  http.post(
    `${API}/messages`,
    withSession(
      async ({ session, db, request }) => {
        const body = await readJson<Schemas['PortalMessageCreate']>(request);
        const text = body.text?.trim() ?? '';
        if (!text) return error(422, 'TEXT_REQUIRED');
        if (text.length > 4000 || !CLIENT_MESSAGE_ID_RE.test(body.client_message_id ?? '')) {
          return error(422, 'VALIDATION_ERROR');
        }
        const repeat = db.messages.find((message) => message.client_message_id === body.client_message_id);
        if (repeat) return json(repeat, 200);
        if (text === 'fail') return error(503, 'HTTP_503');
        const context = body.context ? contextOf(db, body.context) : null;
        if (body.context && !context) return error(404, 'NOT_FOUND');
        const contact = contactFor(session.role);
        const message: Schemas['PortalMessage'] = {
          id: Math.max(500, ...db.messages.map((item) => item.id)) + 1,
          direction: 'client',
          author_name: contact.name,
          mine: true,
          text,
          context,
          created_at: new Date().toISOString(),
          client_message_id: body.client_message_id ?? null,
          erased: false,
        };
        db.messages = [...db.messages, message];
        return json(message, 201);
      },
      { action: true },
    ),
  ),
  http.post(
    `${API}/messages/read`,
    withSession(async ({ db, request }) => {
      const { last_id } = await readJson<Schemas['PortalMessageReadMark']>(request);
      if (typeof last_id !== 'number' || last_id < 1) return error(422, 'VALIDATION_ERROR');
      if (!db.messages.some((message) => message.id === last_id)) return error(404, 'NOT_FOUND');
      db.readMark = Math.max(db.readMark, last_id);
      return json({ unread: unreadOf(db) } satisfies Schemas['PortalMessageUnread']);
    }),
  ),
  http.get(`${API}/team`, withSession(({ db }) => json(db.team))),
  http.post(
    `${API}/team/invite`,
    withSession(
      async ({ db, request }) => {
        const body = await readJson<Schemas['TeamInvite']>(request);
        if (!body.name?.trim() || !body.language || !body.channels?.length) return error(422, 'VALIDATION_ERROR');
        if (body.channels.includes('email') && !(body.email && EMAIL_RE.test(body.email))) {
          return error(422, 'VALIDATION_ERROR');
        }
        if (body.channels.includes('telegram') && !body.phone?.trim()) return error(422, 'VALIDATION_ERROR');
        if (body.email && db.team.some((member) => member.email === body.email)) return error(422, 'TEAM_MEMBER_EXISTS');
        // Письмо не ушло (контракт 0.3.0): коллега не добавлен, повторить можно сразу.
        if (body.email?.startsWith('delivery-fail')) return error(503, 'DELIVERY_FAILED');
        const member: Schemas['TeamMember'] = {
          id: Math.max(100, ...db.team.map((item) => item.id)) + 1,
          name: body.name,
          email: body.email ?? null,
          phone: body.phone ?? null,
          has_telegram: false,
          language: body.language,
          preferred_channel: body.channels.length > 1 ? 'both' : body.channels[0],
          can_act: body.can_act ?? false,
          is_primary: false,
          invited_at: new Date().toISOString(),
          last_login_at: null,
        };
        db.team = [...db.team, member];
        return json(member, 201);
      },
      { action: true },
    ),
  ),
  http.patch(
    `${API}/team/:id`,
    withSession(
      async ({ db, params, request, session }) => {
        const currentContact = contactFor(session.role);
        if (!currentContact.is_admin) return error(403, 'ADMIN_REQUIRED');
        const { id } = params as { id: string };
        const memberId = Number(id);
        const member = db.team.find((m) => m.id === memberId);
        if (!member) return error(404, 'NOT_FOUND');
        const body = await readJson<Schemas['TeamMemberUpdate']>(request);
        if (member.is_primary && body.is_admin === false) return error(422, 'CANNOT_MODIFY_PRIMARY_CONTACT');
        if (member.is_primary && body.can_act === false) return error(422, 'CANNOT_MODIFY_PRIMARY_CONTACT');
        if (body.is_admin === false && member.is_admin) {
          const otherAdmins = db.team.filter((m) => m.is_admin && m.id !== memberId);
          if (otherAdmins.length === 0) return error(422, 'LAST_ADMIN_CANNOT_BE_REMOVED');
        }
        if (body.can_act !== undefined) member.can_act = body.can_act;
        if (body.is_admin !== undefined) member.is_admin = body.is_admin;
        return json(member);
      },
      { action: true },
    ),
  ),
  http.post(
    `${API}/team/:id/deactivate`,
    withSession(
      async ({ db, params, session }) => {
        const currentContact = contactFor(session.role);
        if (!currentContact.is_admin) return error(403, 'ADMIN_REQUIRED');
        const { id } = params as { id: string };
        const memberId = Number(id);
        if (memberId === currentContact.id) return error(422, 'CANNOT_DEACTIVATE_SELF');
        const member = db.team.find((m) => m.id === memberId);
        if (!member) return error(404, 'NOT_FOUND');
        if (member.is_primary) return error(422, 'CANNOT_MODIFY_PRIMARY_CONTACT');
        if (member.is_admin) {
          const otherAdmins = db.team.filter((m) => m.is_admin && m.id !== memberId);
          if (otherAdmins.length === 0) return error(422, 'LAST_ADMIN_CANNOT_BE_REMOVED');
        }
        db.team = db.team.filter((m) => m.id !== memberId);
        return json({ ok: true, deactivated_contact_id: memberId });
      },
      { action: true },
    ),
  ),
  // --- «Мои товары» партнёра (модуль my_products, PART-2) ---------------------------------------
  http.get(
    `${API}/partner/products`,
    withSession(({ db, request }) => {
      const url = new URL(request.url);
      const status = url.searchParams.get('status');
      const q = url.searchParams.get('q')?.trim().toLowerCase() ?? '';
      const page = Math.max(1, Number(url.searchParams.get('page') ?? 1) || 1);
      const pageSize = Math.min(100, Math.max(1, Number(url.searchParams.get('page_size') ?? 20) || 20));
      if (status && !['draft', 'review', 'returned', 'published', 'matched'].includes(status)) return error(422, 'VALIDATION_ERROR');
      const searched = db.partnerProducts.filter(
        (item) =>
          !q || item.name.toLowerCase().includes(q) || item.manufacturer_part_number.toLowerCase().includes(q) || (item.brand ?? '').toLowerCase().includes(q),
      );
      const found = status ? searched.filter((item) => item.status === status) : searched;
      const body: Schemas['PartnerProductPage'] = {
        items: found.slice((page - 1) * pageSize, page * pageSize),
        page,
        page_size: pageSize,
        total: found.length,
        counts: partner.statusCounts(searched),
        attention: partner.attention(db.partnerProducts),
      };
      return json(body);
    }),
  ),
  http.get<IdParams>(
    `${API}/partner/products/:id`,
    withSession<IdParams>(({ db, params }) => {
      const item = byId(db.partnerProducts, params.id);
      return item ? json(partner.detailOf(item)) : error(404, 'NOT_FOUND');
    }),
  ),
  http.post(
    `${API}/partner/products/submit`,
    withSession(
      async ({ db, request }) => {
        const body = await readJson<{ ids: number[] }>(request);
        if (!Array.isArray(body.ids) || body.ids.length === 0 || body.ids.length > 500) return error(422, 'VALIDATION_ERROR');
        return json(partner.submitIds(db.partnerProducts, body.ids));
      },
      { action: true },
    ),
  ),
  http.post(
    `${API}/partner/offers/confirm`,
    withSession(
      async ({ db, request }) => {
        const body = await readJson<{ ids?: number[]; all?: boolean }>(request);
        const byIds = Array.isArray(body.ids) && body.ids.length > 0;
        if (byIds === Boolean(body.all)) return error(422, 'VALIDATION_ERROR');
        return json(partner.confirmIds(db.partnerProducts, body.all ? null : (body.ids as number[])));
      },
      { action: true },
    ),
  ),
  http.get(
    `${API}/partner/price-template`,
    withSession(
      () =>
        new HttpResponse(new Uint8Array([0x50, 0x4b, 0x03, 0x04]), {
          headers: {
            'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'Content-Disposition': 'attachment; filename="catalog_template.xlsx"',
          },
        }),
    ),
  ),
  http.post(
    `${API}/partner/price-list`,
    withSession(
      async ({ db, request }) => {
        const form = await request.formData();
        const file = form.get('file');
        if (!(file instanceof File)) return error(400, 'FILE_REQUIRED');
        if (!/\.xlsx$/i.test(file.name)) return error(400, 'XLSX_REQUIRED');
        if (file.size > 20 * 1024 * 1024) return error(422, 'FILE_TOO_LARGE');
        const from = String(form.get('valid_from') ?? '');
        const until = String(form.get('valid_until') ?? '');
        if (from && until && until < from) return error(422, 'OFFER_VALIDITY_RANGE_INVALID');
        const taskId = `task_${db.priceTasks.size + 1}`;
        db.priceTasks.set(taskId, partner.newTask(file.name, String(form.get('dry_run')) === 'true'));
        return json({ task_id: taskId } satisfies Schemas['PriceListAccepted'], 202);
      },
      { action: true },
    ),
  ),
  http.get<{ taskId: string }>(
    `${API}/partner/price-list/:taskId`,
    withSession<{ taskId: string }>(({ db, params }) => {
      const task = db.priceTasks.get(params.taskId);
      return task ? json(partner.taskView(params.taskId, task, db.partnerProducts)) : error(404, 'NOT_FOUND');
    }),
  ),

  // Публичная проверка официальных документов (ADR-0024 §6, SIGN-VERIFY-1)
  http.get<{ code: string }>(`${API}/verify/:code`, ({ params }) => {
    const code = String(params.code);
    if (code === 'unknown' || code === 'not-found' || code === 'unknown-code-999') {
      return HttpResponse.json({ detail: 'NOT_FOUND' }, { status: 404 });
    }
    if (code === 'rate-limited') {
      return HttpResponse.json({ detail: 'TOO_MANY_REQUESTS' }, { status: 429, headers: { 'Retry-After': '60' } });
    }
    if (code === 'revoked') {
      return HttpResponse.json({
        ...fixtures.mockDocumentVerification,
        code: 'revoked',
        status: 'revoked',
        revoked_at: '2026-11-05T14:00:00Z',
        revocation_reason: 'Отозван в связи с отменой доверенности',
      });
    }
    return HttpResponse.json({
      ...fixtures.mockDocumentVerification,
      code,
    });
  }),

  // Публичная форма CRM «Запрос» со страницы «Я новый клиент» (M2-CAB-03) — src/mocks/crmForm.ts.

  ...crmFormHandlers,
];
