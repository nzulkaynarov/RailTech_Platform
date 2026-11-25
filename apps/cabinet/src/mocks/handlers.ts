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
 * Документ по ссылке из письма (ДК-1, ДК-2): токен `/d/<токен>` — `revoked…` → 410 `DOC_LINK_REVOKED`, `expired…` →
 * 410 `DOC_LINK_EXPIRED`, `superseded…` → 410 `DOC_LINK_SUPERSEDED`, `unknown…` или короче 16 знаков → 404; `viewer…` —
 * получатель без права действовать; `foreign…` — ссылка другой компании (сессия видит гостевой вид); `done…` — КП уже принято;
 * `toosoon…` — повтор кода раньше срока (429). Код: `000000` — неверный, `111111` — пять неверных подряд, иной — вход.
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
    letters: empty ? [] : structuredClone(fixtures.letters),
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
    partnerOrders: empty ? [] : partner.partnerOrders(),
    partnerPriceRequests: empty ? [] : partner.partnerPriceRequests(),
  };
}

type Db = ReturnType<typeof createDb>;
let dbs: Record<Dataset, Db> = { demo: createDb('demo'), empty: createDb('empty') };

/** Для тестов: чистая сессия и данные фикстур. */
export function resetMockPortal(): void {
  setMockSession(null);
  docLinkStates.clear();
  dbs = { demo: createDb('demo'), empty: createDb('empty') };
  resetMockCrmForm();
  resetMockLegal();
}

/** Для тестов: состояние Telegram контакта в данных демо-компании (статус, доступность, авто-привязка). */
export function setMockTelegram(patch: Partial<fixtures.TelegramMock>): void {
  Object.assign(dbs.demo.telegram, patch);
}

/** Для тестов: заявка на партнерство для компании. */
export function setMockPartnerApplication(app: Schemas['PartnerApplication'] | null): void {
  dbs.demo.partnerApplication = app;
}

/** Новый счёт запроса — только администратору, как в ERP (FX-4). */
function companyView(company: Schemas['Company'], isAdmin: boolean | undefined): Schemas['Company'] {
  const change = company.bank_change_request;
  if (!change || isAdmin) return company;
  return { ...company, bank_change_request: { ...change, new_bank_details: null, new_bank_account: null } };
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
    legal_pending: legalPending(),
  };
}

// --- Оферта и политика Кабинета (ДВ-5) --------------------------------------------------------------------------
// По умолчанию в моке ничего не опубликовано — кабинет открыт, как в ERP до первой публикации. `setMockLegal` (тесты) или
// `sessionStorage['cabinet.mock.legal']` (dev, снимки) включает публикацию; принятие запоминается в той же записи.

const LEGAL_KEY = 'cabinet.mock.legal';
export interface MockLegal {
  published: boolean;
  accepted: boolean;
}
let memoryLegal: MockLegal = { published: false, accepted: false };

function readLegal(): MockLegal {
  try {
    const raw = window.sessionStorage.getItem(LEGAL_KEY);
    return raw ? (JSON.parse(raw) as MockLegal) : memoryLegal;
  } catch {
    return memoryLegal;
  }
}

export function setMockLegal(state: MockLegal): void {
  memoryLegal = state;
  try {
    window.sessionStorage.setItem(LEGAL_KEY, JSON.stringify(state));
  } catch {
    // Хранилище недоступно — состояние живёт до перезагрузки.
  }
}

/** Тесты: вернуть «ничего не опубликовано». */
export function resetMockLegal(): void {
  memoryLegal = { published: false, accepted: false };
  try {
    window.sessionStorage.removeItem(LEGAL_KEY);
  } catch {
    // нет хранилища
  }
}

function legalPending(): boolean {
  const state = readLegal();
  return state.published && !state.accepted;
}

function legalCurrent(): Schemas['LegalCurrent'] {
  const state = readLegal();
  if (!state.published) return { needs_acceptance: false, editions: [] };
  return {
    needs_acceptance: !state.accepted,
    editions: fixtures.legalEditions().map((edition) => ({ ...edition, accepted: state.accepted })),
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
  if (!number) return null;
  return ref.kind === 'deal'
    ? { kind: ref.kind, id: ref.id, number, stage: fixtures.deals[ref.id]?.stage }
    : { kind: ref.kind, id: ref.id, number };
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
        ? { roles: ['partner'], modules: ['my_products', 'letters', 'messages', 'profile'] }
        : token.includes('partner')
          ? { roles: ['partner'], modules: ['my_products', 'catalog_requests', 'letters', 'messages', 'profile'] }
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
  { action = false, legalExempt = false }: { action?: boolean; legalExempt?: boolean } = {},
) {
  return ({ params, request }: { params: P; request: Request }) => {
    const session = readSession();
    if (!session) return error(401, 'UNAUTHORIZED');
    // ДВ-5: как в ERP — без принятия действующих оферты и политики открыты только профиль и сами документы
    if (!legalExempt && legalPending()) return error(403, 'LEGAL_ACCEPTANCE_REQUIRED');
    if (action && !contactFor(session.role).can_act) return error(403, 'FORBIDDEN');
    return resolver({ session, db: dbOf(session), params, request });
  };
}

type IdParams = { id: string };

function byId<T extends { id: number }>(items: T[], id: string): T | undefined {
  return items.find((item) => String(item.id) === id);
}

/** ЕД-4: позиция строки каталога — наш артикул и главное фото (id = 1, если у карточки мока есть фото). */
function withItemRef(item: Schemas['CatalogItem']): Schemas['CatalogItem'] {
  return {
    ...item,
    item: {
      id: item.id,
      name: item.name,
      sku: `RT-0${String(item.id)}`,
      kind: item.kind,
      photo: item.images?.[0] ? 1 : null,
    },
  };
}

/** Карточка в списке каталога — без документов (они только в детальной карточке). */
function listItem(item: Schemas['CatalogItem']): Schemas['CatalogItem'] {
  const copy = withItemRef(item);
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

const MOCK_BANKS: Record<string, { name: string; swift: string }> = {
  '00014': { name: 'АКБ «Демо Банк»', swift: 'DEMOUZ22' },
  '00440': { name: 'АКБ «Узпромстройбанк»', swift: '' },
};

const NEW_DEVICE_EVENT_ID = 2;
const ENDED_SESSIONS = new WeakMap<Db, Set<number>>();
const endedSessions = (db: Db): Set<number> => {
  let ended = ENDED_SESSIONS.get(db);
  if (!ended) ENDED_SESSIONS.set(db, (ended = new Set()));
  return ended;
};

// --- Документ по ссылке из письма (ДК-1, ДК-2) --------------------------------------------------------------------

/** Что решено по КП ссылки: токен → `accepted` / `rejected`; нет записи — ждёт ответа (`done…` — уже принято). */
const docLinkStates = new Map<string, 'accepted' | 'rejected' | 'answered' | 'confirmed'>();
const DOC_LINK_MIN = 16;

function docLinkGone(token: string): Response | null {
  if (token.length < DOC_LINK_MIN || token.startsWith('unknown')) return error(404, 'NOT_FOUND');
  if (token.startsWith('revoked')) return error(410, 'DOC_LINK_REVOKED');
  if (token.startsWith('expired')) return error(410, 'DOC_LINK_EXPIRED');
  if (token.startsWith('superseded')) return error(410, 'DOC_LINK_SUPERSEDED');
  return null;
}

type DocKind = 'quote' | 'contract' | 'invoice' | 'act' | 'price_request' | 'supplier_order';

/** Вид документа мока по началу токена (ДК-3, ДК-5): `contract-…`, `invoice-…`, `act-…`, `rfq-…`, `order-…`; прочее — КП. */
function docKind(token: string): DocKind {
  if (token.startsWith('rfq')) return 'price_request';
  if (token.startsWith('order')) return 'supplier_order';
  return (['contract', 'invoice', 'act'] as const).find((kind) => token.startsWith(kind)) ?? 'quote';
}

/** Что можно сделать по ссылке у вида — как `actions` ответа сервера. */
const DOC_ACTIONS: Record<DocKind, Array<'accept' | 'reject' | 'question' | 'answer' | 'confirm'>> = {
  quote: ['accept', 'reject', 'question'],
  contract: ['accept'],
  invoice: [],
  act: ['accept', 'reject'],
  price_request: ['answer'],
  supplier_order: ['confirm'],
};

function docLinkState(token: string): string {
  const decided = docLinkStates.get(token);
  if (decided) return decided;
  if (token.includes('paid')) return 'paid';
  if (token.includes('cancelled')) return 'cancelled';
  if (token.includes('done')) {
    const kind = docKind(token);
    return kind === 'price_request' ? 'answered' : kind === 'supplier_order' ? 'confirmed' : 'accepted';
  }
  return 'open';
}

function docLinkAvailability(token: string, session: MockSession | null): Schemas['DocLinkAvailability'] {
  const state = docLinkState(token);
  if (DOC_ACTIONS[docKind(token)].length === 0) return { allowed: false, reason: 'no_actions' };
  if (state !== 'open') return { allowed: false, reason: state };
  if (session && token.includes('foreign')) return { allowed: false, reason: 'other_company' };
  const canAct = session ? contactFor(session.role).can_act : !token.includes('viewer');
  return canAct ? { allowed: true, reason: null } : { allowed: false, reason: 'no_right' };
}

function docLinkView(token: string): Schemas['DocLinkView'] {
  const session = readSession();
  const quote = fixtures.quotes[0];
  const availability = docLinkAvailability(token, session);
  const valid = new Date(`${businessToday()}T00:00:00Z`);
  valid.setUTCDate(valid.getUTCDate() + 16);
  const expires = new Date(valid);
  expires.setUTCDate(expires.getUTCDate() + 30);
  const kind = docKind(token);
  const common = {
    from_name: 'ООО «РейлТех»',
    to_name: 'ООО «Восток Транс»',
    version: 1,
    valid_until: null,
    state: docLinkState(token) as Schemas['DocLinkView']['state'],
    link_expires_at: expires.toISOString(),
    recipient_hint: 'p***@vostok-trans.uz',
    session: (!session ? 'none' : token.includes('foreign') ? 'other_company' : 'member') as Schemas['DocLinkView']['session'],
    decide: availability,
    ask: availability,
    actions: DOC_ACTIONS[kind],
    lines: [],
  };
  const total = { amount: '33000000.00', currency: 'UZS' };
  if (kind === 'price_request' || kind === 'supplier_order') return partnerDocLinkView(kind, common, total, token.includes('nodate'));
  if (kind === 'contract') {
    return { ...common, kind, number: 'CT-0042', total, signed_at: common.state === 'accepted' ? valid.toISOString() : null };
  }
  if (kind === 'invoice') {
    const paid = common.state === 'paid';
    return {
      ...common,
      kind,
      number: 'INV-0077',
      total,
      due_date: valid.toISOString().slice(0, 10),
      paid: paid ? total : { amount: '0.00', currency: 'UZS' },
      balance_due: paid ? { amount: '0.00', currency: 'UZS' } : total,
      payment_details: 'Получатель: ООО «РейлТех»\nР/с 2020 8000 1234 5678 9001, МФО 00014\nНазначение: оплата по счёту INV-0077',
    };
  }
  if (kind === 'act') {
    return { ...common, kind, number: 'ACT-0031', total, issued_at: valid.toISOString() };
  }
  return {
    ...common,
    kind,
    number: 'QT-0118',
    total: quote.total,
    subtotal: quote.subtotal,
    vat: quote.vat,
    valid_until: valid.toISOString().slice(0, 10),
    payment_terms: quote.payment_terms,
    delivery_days: quote.delivery_days,
    delivery_note: quote.delivery_note,
    lines: quote.lines,
  };
}

/** ДК-5: запрос цены и заказ глазами партнёра — его позиции и цены; клиента заявки и нашей цены продажи в ответе нет. */
function partnerDocLinkView(
  kind: 'price_request' | 'supplier_order',
  common: Omit<Schemas['DocLinkView'], 'kind' | 'number' | 'total'>,
  total: Schemas['Money'],
  noDate: boolean,
): Schemas['DocLinkView'] {
  const order = kind === 'supplier_order';
  const answered = common.state === 'answered';
  const money = (amount: string) => ({ amount, currency: 'UZS' });
  const lines: Schemas['DocLinkPartnerLine'][] = [
    {
      id: 11,
      position: 1,
      name: 'Рельс Р65, ГОСТ Р 51685',
      article: 'Р65-25',
      unit: 'т',
      quantity: '12',
      unit_price: order ? money('2500000.00') : answered ? money('2480000.00') : null,
      total: order ? money('30000000.00') : null,
      lead_days: answered ? 14 : null,
    },
    {
      id: 12,
      position: 2,
      name: 'Накладка двухголовая',
      article: 'НД-4',
      unit: 'шт.',
      quantity: '40',
      unit_price: order ? money('75000.00') : answered ? money('74000.00') : null,
      total: order ? money('3000000.00') : null,
      lead_days: answered ? 21 : null,
    },
  ];
  return {
    ...common,
    kind,
    number: order ? 'ЗП-2026-031' : 'Рельс Р65 и ещё 1 позиция',
    from_name: 'ООО «РейлТех»',
    to_name: 'ООО «Вымышленная Сталь»',
    total: order ? total : money('0.00'),
    partner_lines: lines,
    partner_note: order ? 'Отгрузка на склад в Ташкенте, сертификаты — с первой партией.' : 'Нужны сертификаты соответствия.',
    expected_date: order && !noDate ? businessToday() : null,
    confirmed_at: common.state === 'confirmed' ? new Date().toISOString() : null,
    answered_at: answered ? new Date().toISOString() : null,
    answer_note: answered ? 'Цена действует до конца месяца.' : null,
  };
}

const docLinkHandlers = [
  http.post(`${API}/doc-links/open`, async ({ request }) => {
    const { token } = await readJson<{ token?: string }>(request);
    if (typeof token !== 'string' || !token) return error(422, 'VALIDATION_ERROR');
    return docLinkGone(token) ?? json(docLinkView(token));
  }),
  http.post(`${API}/doc-links/pdf`, async ({ request }) => {
    const { token } = await readJson<{ token?: string }>(request);
    if (typeof token !== 'string' || !token) return error(422, 'VALIDATION_ERROR');
    const gone = docLinkGone(token);
    if (gone) return gone;
    return new HttpResponse(new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x34]), {
      headers: { 'Content-Type': 'application/pdf', 'Content-Disposition': 'attachment; filename="QT-0118.pdf"' },
    });
  }),
  http.post(`${API}/doc-links/code`, async ({ request }) => {
    const { token } = await readJson<{ token?: string }>(request);
    if (typeof token !== 'string' || !token) return error(422, 'VALIDATION_ERROR');
    const gone = docLinkGone(token);
    if (gone) return gone;
    if (token.startsWith('toosoon')) {
      return HttpResponse.json({ detail: 'CODE_RESEND_TOO_SOON' }, { status: 429, headers: { 'Retry-After': '30' } });
    }
    const channels: Schemas['DocLinkCodeSent']['channels'] = token.startsWith('tg') ? ['email', 'telegram'] : ['email'];
    return json({ sent_to: 'p***@vostok-trans.uz', expires_in: 600, resend_after: 45, channels } satisfies Schemas['DocLinkCodeSent'], 202);
  }),
  http.post(`${API}/doc-links/verify`, async ({ request }) => {
    const { token, code } = await readJson<{ token?: string; code?: string }>(request);
    if (typeof token !== 'string' || !/^\d{6}$/.test(code ?? '')) return error(422, 'VALIDATION_ERROR');
    const gone = docLinkGone(token);
    if (gone) return gone;
    if (code === '000000') return error(422, 'LOGIN_CODE_INVALID');
    if (code === '111111') return error(429, 'LOGIN_CODE_LOCKED');
    const session = sessionFromToken(token, 'magic_link');
    setMockSession(session);
    return json(me(session));
  }),
  http.post(
    `${API}/doc-links/act`,
    withSession(
      async ({ request }) => {
        const { token, action, text } = await readJson<{ token?: string; action?: string; text?: string }>(request);
        if (typeof token !== 'string' || !['accept', 'reject', 'question', 'answer', 'confirm'].includes(action ?? '')) {
          return error(422, 'VALIDATION_ERROR');
        }
        const gone = docLinkGone(token);
        if (gone) return gone;
        if (token.includes('foreign')) return error(403, 'FORBIDDEN');
        if (!DOC_ACTIONS[docKind(token)].includes(action as 'accept')) return error(422, 'VALIDATION_ERROR');
        if (docLinkState(token) !== 'open') {
          return error(409, action === 'answer' ? 'ALREADY_ANSWERED' : action === 'confirm' ? 'TRANSITION_NOT_ALLOWED' : 'QUOTE_FINALIZED');
        }
        if (action === 'answer' && !text?.trim()) return error(422, 'TEXT_REQUIRED');
        if (action === 'reject' || action === 'question') {
          if (!text?.trim()) return error(422, action === 'reject' ? 'REASON_REQUIRED' : 'TEXT_REQUIRED');
        }
        if (action === 'accept') docLinkStates.set(token, 'accepted');
        if (action === 'reject') docLinkStates.set(token, 'rejected');
        if (action === 'answer') docLinkStates.set(token, 'answered');
        if (action === 'confirm') docLinkStates.set(token, 'confirmed');
        return json(docLinkView(token));
      },
      { action: true },
    ),
  ),
];

export const handlers = [
  ...docLinkHandlers,
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
    return json({ status: 'ok', sent: true, email: body.email });
  }),
  // Файл-предупреждение о плановом обновлении (DECISIONS 2026-11-23): в проде его отдаёт Caddy; в моке — 404, баннера нет.
  http.get('/maintenance.json', () => new HttpResponse(null, { status: 404 })),
  // Название оператора до входа (задача «Н3a2»): в CRM — «Настройки · Компания».
  http.get(`${API}/operator`, () => HttpResponse.json({ name: 'RailTech', bot_username: 'railtech_test_bot', logo_url: null })),
  // Оферта и политика Кабинета (ДВ-5): до принятия остальные эндпоинты отвечают 403 `LEGAL_ACCEPTANCE_REQUIRED` (`withSession`).
  http.get(`${API}/legal/policy`, () =>
    json({ policy: readLegal().published ? (fixtures.legalEditions().find((e) => e.kind === 'privacy') ?? null) : null }),
  ),
  http.get(
    `${API}/legal`,
    withSession(() => json(legalCurrent()), { legalExempt: true }),
  ),
  http.post(
    `${API}/legal/accept`,
    withSession(
      async ({ request }) => {
        const body = await readJson<{ edition_ids: number[]; language: string }>(request);
        const current = legalCurrent().editions.map((edition) => edition.id).sort();
        const sent = [...(body.edition_ids ?? [])].sort();
        if (!['ru', 'uz', 'en'].includes(body.language ?? '')) return error(422, 'VALIDATION_ERROR');
        if (current.length === 0 || current.join() !== sent.join()) return error(409, 'LEGAL_EDITION_CHANGED');
        setMockLegal({ published: true, accepted: true });
        return json(legalCurrent());
      },
      { legalExempt: true },
    ),
  ),
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
    withSession(
      () => {
        setMockSession(null);
        return new HttpResponse(null, { status: 204 });
      },
      { legalExempt: true },
    ),
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
  http.get(`${API}/me`, withSession(({ session }) => json(me(session)), { legalExempt: true })),
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
          number: `ЗВ-2026-${String(nextId - 400).padStart(3, '0')}`,
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
        // Как ERP (СЦ-10): только свои непривязанные загрузки; привязанная к заявке повторно не используется.
        const refs = body.attachments ?? [];
        if (refs.some((ref) => !db.uploads.has(ref.upload_id))) return error(422, 'UPLOAD_NOT_FOUND');
        for (const ref of refs) db.uploads.delete(ref.upload_id);
        const nextId = Math.max(500, ...db.requests.map((item) => item.id)) + 1;
        const created: Schemas['ClientRequest'] = {
          id: nextId,
          number: `ЗВ-2026-${String(nextId - 400).padStart(3, '0')}`,
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
          ? { channel: 'telegram', sent_to: 'Telegram', expires_in: 900, delivery: null }
          : { channel: 'email', sent_to: maskEmail(contact.email ?? ''), expires_in: 900, delivery: '1' };
        return json(sent, 202);
      },
      { action: true },
    ),
  ),
  // 0.10 (FR-12): итог письма с кодом — на стенде MSW почта работает, письмо «отправлено».
  http.get<IdParams & { delivery: string }>(
    `${API}/quotes/:id/code-delivery/:delivery`,
    withSession<IdParams & { delivery: string }>(({ db, params }) => {
      if (!byId(db.quotes, params.id)) return error(404, 'NOT_FOUND');
      const result: Schemas['CodeDelivery'] = { state: 'sent', reason: null };
      return json(result);
    }),
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

  // --- письма компании (ADR-0026) -----------------------------------------------------------------
  http.get(
    `${API}/letters`,
    withSession(({ db, request }) => {
      const url = new URL(request.url);
      const direction = url.searchParams.get('direction');
      const q = (url.searchParams.get('q') || '').trim().toLowerCase();
      const list = db.letters.filter(
        (letter) =>
          (!direction || letter.direction === direction) &&
          (!q || letter.number.toLowerCase().includes(q) || letter.subject.toLowerCase().includes(q)),
      );
      return json(list);
    }),
  ),
  http.get<IdParams>(
    `${API}/letters/:id/file`,
    withSession<IdParams>(({ db, params }) => {
      const letter = byId(db.letters, params.id);
      if (!letter || !letter.has_file) return error(404, 'NOT_FOUND');
      const fileName = `${letter.number.replace('/', '-')}.pdf`;
      return new HttpResponse('%PDF-1.4\n% mock letter\n', {
        headers: { 'Content-Type': 'application/pdf', 'Content-Disposition': `inline; filename*=UTF-8''${fileName}` },
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
  // ЕД-4: миниатюра — первое фото позиции каталога мока (SVG как есть); нет позиции или фото — 404, как в ERP
  http.get<IdParams>(
    `${API}/items/:id/thumbnail`,
    withSession<IdParams>(({ db, params }) => {
      const src = db.catalog.find((item) => item.id === Number(params.id))?.images?.[0];
      if (!src?.startsWith('data:image/svg+xml;utf8,')) return error(404, 'NOT_FOUND');
      return new HttpResponse(decodeURIComponent(src.slice('data:image/svg+xml;utf8,'.length)), {
        headers: { 'Content-Type': 'image/svg+xml' },
      });
    }),
  ),
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
      return item ? json(withItemRef(item)) : error(404, 'NOT_FOUND');
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
  // Справочник банков ЦБ (ADR-0029): вымышленные МФО; остальные — «нет в справочнике»
  http.get<{ mfo: string }>(
    `${API}/company/bank-directory/:mfo`,
    withSession<{ mfo: string }>(({ params }) => {
      const bank = MOCK_BANKS[params.mfo];
      return json({ bank: bank ? { mfo: params.mfo, ...bank } : null });
    }),
  ),
  http.get(
    `${API}/company`,
    withSession(({ db, session }) => json(companyView(db.company, contactFor(session.role).is_admin))),
  ),
  http.get(
    `${API}/company/security-log`,
    withSession(({ db, session }) => {
      const currentContact = contactFor(session.role);
      if (!currentContact.is_admin) return error(403, 'ADMIN_REQUIRED');
      return json({
        items: [
          {
            id: 1,
            event_type: 'login',
            created_at: new Date(Date.now() - 3600_000).toISOString(),
            actor_name: currentContact.name,
            actor_email: currentContact.email,
            ip_address: '192.168.1.10',
            user_agent: 'Mozilla/5.0 Chrome/120',
            target_name: null,
            details: 'Вход в систему',
            can_end_session: false,
          },
          // ДВ-6: вход коллеги с нового устройства — администратор может завершить сеанс
          {
            id: NEW_DEVICE_EVENT_ID,
            event_type: 'login_new_device',
            created_at: new Date(Date.now() - 600_000).toISOString(),
            actor_name: 'Алишер Юсупов',
            actor_email: 'a.yusupov@example.uz',
            ip_address: '84.54.10.20',
            user_agent: 'Mozilla/5.0 (Windows NT 10.0) Chrome/131.0',
            target_name: null,
            details: 'Chrome · Windows',
            can_end_session: !endedSessions(db).has(NEW_DEVICE_EVENT_ID),
          },
        ],
      });
    }),
  ),
  http.post<{ id: string }>(
    `${API}/company/security-log/:id/end-session`,
    withSession<{ id: string }>(({ db, session, params }) => {
      if (!contactFor(session.role).is_admin) return error(403, 'ADMIN_REQUIRED');
      const id = Number(params.id);
      if (id !== NEW_DEVICE_EVENT_ID) return error(404, 'NOT_FOUND');
      if (endedSessions(db).has(id)) return error(409, 'SESSION_ALREADY_ENDED');
      endedSessions(db).add(id);
      return new HttpResponse(null, { status: 204 });
    }),
  ),
  http.put(
    `${API}/company`,
    withSession(
      async ({ db, session, request }) => {
        const body = await readJson<Schemas['CompanyUpdate']>(request);
        if (body.name !== undefined && !body.name.trim()) return error(422, 'VALIDATION_ERROR');
        if (body.inn !== undefined && body.inn !== '' && !/^\d{9,14}$/.test(body.inn)) return error(422, 'INN_INVALID');
        const { bank_account: requested, ...profile } = body;
        if (requested !== undefined) {
          const currentContact = contactFor(session.role);
          if (!currentContact.is_admin) return error(409, 'ADMIN_REQUIRED');
          if (db.company.bank_change_request?.status === 'pending') return error(409, 'BANK_CHANGE_ALREADY_PENDING');
          const noticeId = (db.notifications[0]?.id ?? 0) + 1;
          db.company.bank_change_request = {
            id: noticeId,
            status: 'pending',
            requested_by_name: currentContact.name || currentContact.email || 'Admin',
            new_bank_details: `Расчётный счёт: ${requested.account.replace(/(.{4})(?=.)/g, '$1 ')}`,
            new_bank_account: requested,
            created_at: new Date().toISOString(),
            decided_at: null,
            reject_reason: null,
          };
          db.notifications.unshift({
            id: noticeId,
            kind: 'bank_requisites_change_requested',
            group: 'security',
            object: { type: 'bank_change', id: noticeId, number: null },
            action: 'awaiting_decision',
            text_key: 'bank_requisites_change_requested',
            params: { actor: currentContact.name || currentContact.email || 'Admin' },
            link: '/company',
            created_at: new Date().toISOString(),
            read_at: null,
          });
        }
        const country = body.country_code
          ? { code: body.country_code, name: body.country_code === 'UZ' ? 'Узбекистан' : 'Казахстан' }
          : db.company.country;
        db.company = { ...db.company, ...profile, country };
        return json(companyView(db.company, contactFor(session.role).is_admin));
      },
      { action: true },
    ),
  ),
  // ЕД-5: логотип компании — версия в `company.logo_version`, картинка — SVG по тому же адресу
  http.get(
    `${API}/company/logo`,
    withSession(({ db }) => {
      if (!db.company.logo_version) return error(404, 'NOT_FOUND');
      return new HttpResponse(
        '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96"><rect width="96" height="96" rx="8" fill="#1d6b8a"/><rect x="20" y="58" width="56" height="8" fill="#fff"/><rect x="42" y="24" width="12" height="42" fill="#fff"/></svg>',
        { headers: { 'Content-Type': 'image/svg+xml' } },
      );
    }),
  ),
  http.put(
    `${API}/company/logo`,
    withSession(
      async ({ db, session, request }) => {
        if (!contactFor(session.role).is_admin) return error(409, 'ADMIN_REQUIRED');
        const file = (await request.formData()).get('file');
        if (!file || typeof file === 'string') return error(400, 'FILE_REQUIRED');
        if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) return error(422, 'FILE_TYPE_NOT_ALLOWED');
        if (file.size > 2 * 1024 * 1024) return error(422, 'FILE_TOO_LARGE');
        db.company = { ...db.company, logo_version: `v${(Number(db.company.logo_version?.slice(1)) || 0) + 1}` };
        return json(companyView(db.company, true));
      },
      { action: true },
    ),
  ),
  http.delete(
    `${API}/company/logo`,
    withSession(
      ({ db, session }) => {
        if (!contactFor(session.role).is_admin) return error(409, 'ADMIN_REQUIRED');
        db.company = { ...db.company, logo_version: null };
        return json(companyView(db.company, true));
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
    `${API}/company/partner-application/return`,
    withSession(
      async ({ db, request }) => {
        if (!db.partnerApplication || db.partnerApplication.status !== 'contract_sent') {
          return error(400, 'NOT_IN_CONTRACT_SENT_STATUS');
        }
        const body = ((await readJson<{ notes?: string }>(request).catch(() => ({}))) || {}) as { notes?: string };
        if (!body.notes?.trim()) return error(400, 'RETURN_NOTE_REQUIRED');
        db.partnerApplication.candidate_notes = body.notes;
        db.partnerApplication.candidate_returned_at = new Date().toISOString();
        return json(db.partnerApplication);
      },
      { action: true },
    ),
  ),
  http.post(
    `${API}/company/partner-application/signed-scan`,
    withSession(
      async ({ db }) => {
        if (!db.partnerApplication || db.partnerApplication.status !== 'candidate_agreed') {
          return error(400, 'SCAN_NOT_EXPECTED');
        }
        db.partnerApplication.has_signed_scan = true;
        db.partnerApplication.signed_scan_at = new Date().toISOString();
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
  http.get<IdParams>(
    `${API}/partner/products/:id/documents`,
    withSession<IdParams>(({ db, params }) => {
      const item = byId(db.partnerProducts, params.id);
      return item ? json(partner.documentsOf(item.id)) : error(404, 'NOT_FOUND');
    }),
  ),
  http.post<IdParams>(
    `${API}/partner/products/:id/documents`,
    withSession<IdParams>(
      async ({ db, params, request }) => {
        const item = byId(db.partnerProducts, params.id);
        if (!item) return error(404, 'NOT_FOUND');
        const contentType = request.headers.get('content-type') || '';
        let title: string;
        let kind: string;
        let number: string;
        let validUntil: string;
        let fileName = 'document.pdf';
        let sizeBytes = 102400;

        if (contentType.includes('multipart/form-data')) {
          const form = await request.formData();
          const file = form.get('file');
          if (file instanceof File) {
            fileName = file.name;
            sizeBytes = file.size;
          }
          title = String(form.get('title') || fileName);
          kind = String(form.get('kind') || 'certificate');
          number = String(form.get('number') || '');
          validUntil = String(form.get('valid_until') || '');
        } else {
          const body = await readJson<{ title?: string; kind?: string; number?: string; valid_until?: string }>(request);
          title = body.title || 'document';
          kind = body.kind || 'certificate';
          number = body.number || '';
          validUntil = body.valid_until || '';
        }
        const doc = partner.addDocument(item.id, {
          title,
          kind,
          number,
          valid_until: validUntil || null,
          file_name: fileName,
          size_bytes: sizeBytes,
        });
        return json(doc, 201);
      },
      { action: true },
    ),
  ),
  http.delete<IdParams & { docId: string }>(
    `${API}/partner/products/:id/documents/:docId`,
    withSession<IdParams & { docId: string }>(
      ({ db, params }) => {
        const item = byId(db.partnerProducts, params.id);
        if (!item) return error(404, 'NOT_FOUND');
        const deleted = partner.deleteDocument(item.id, Number(params.docId));
        return deleted ? new HttpResponse(null, { status: 204 }) : error(404, 'NOT_FOUND');
      },
      { action: true },
    ),
  ),
  http.get<IdParams & { docId: string }>(
    `${API}/partner/products/:id/documents/:docId/file`,
    withSession<IdParams & { docId: string }>(({ db, params }) => {
      const item = byId(db.partnerProducts, params.id);
      if (!item) return error(404, 'NOT_FOUND');
      const docs = partner.documentsOf(item.id);
      const doc = docs.find((d) => d.id === Number(params.docId));
      if (!doc) return error(404, 'NOT_FOUND');
      const fileName = `${doc.title.replace(/[^\p{L}\p{N}._-]+/gu, '_')}.pdf`;
      return new HttpResponse('%PDF-1.4\n% mock partner technical document\n', {
        headers: {
          'Content-Type': 'application/pdf',
          'Content-Disposition': `attachment; filename="document.pdf"; filename*=UTF-8''${encodeURIComponent(fileName)}`,
        },
      });
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

  // --- Заказы на поставку (PO, ASN) и запросы цен (RFQ) партнёра (K2-orders) -----------------
  http.get(
    `${API}/partner/orders`,
    withSession(({ db, request }) => {
      const url = new URL(request.url);
      const status = url.searchParams.get('status');
      const q = url.searchParams.get('q')?.trim().toLowerCase() ?? '';
      const page = Math.max(1, Number(url.searchParams.get('page') ?? 1) || 1);
      const pageSize = Math.min(100, Math.max(1, Number(url.searchParams.get('page_size') ?? 20) || 20));
      if (status && !['draft', 'sent', 'confirmed', 'received', 'cancelled'].includes(status)) {
        return error(422, 'VALIDATION_ERROR');
      }
      const searched = db.partnerOrders.filter(
        (item) => !q || item.number.toLowerCase().includes(q) || item.note.toLowerCase().includes(q),
      );
      const found = status ? searched.filter((item) => item.status === status) : searched;
      const items: Schemas['PartnerOrderListItem'][] = found
        .slice((page - 1) * pageSize, page * pageSize)
        .map((row) => ({
          id: row.id,
          number: row.number,
          status: row.status,
          expected_date: row.expected_date,
          created_at: row.created_at,
          sent_at: row.sent_at,
          confirmed_at: row.confirmed_at,
          received_at: row.received_at,
          cancelled_at: row.cancelled_at,
          lines_count: row.lines.length,
          total_amount: row.total_amount,
          currency: row.currency,
        }));
      const body: Schemas['PartnerOrderPage'] = {
        items,
        page,
        page_size: pageSize,
        total: found.length,
        counts: partner.orderStatusCounts(searched),
      };
      return json(body);
    }),
  ),
  http.get<IdParams>(
    `${API}/partner/orders/:id`,
    withSession<IdParams>(({ db, params }) => {
      const item = byId(db.partnerOrders, params.id);
      return item ? json(item) : error(404, 'NOT_FOUND');
    }),
  ),
  http.post<IdParams>(
    `${API}/partner/orders/:id/confirm`,
    withSession<IdParams>(
      async ({ db, params, request }) => {
        const item = byId(db.partnerOrders, params.id);
        if (!item) return error(404, 'NOT_FOUND');
        if (item.status !== 'sent') return error(409, 'TRANSITION_NOT_ALLOWED');
        const body = await readJson<Schemas['PartnerOrderConfirmRequest']>(request);
        if (!body.expected_date) return error(422, 'VALIDATION_ERROR');
        item.status = 'confirmed';
        item.confirmed_at = new Date().toISOString();
        if (!item.expected_date) {
          item.expected_date = body.expected_date;
        } else if (item.expected_date !== body.expected_date) {
          item.date_change = { requested_date: body.expected_date, reason: '', requested_at: item.confirmed_at };
        }
        item.logs.unshift({
          id: Math.max(8200, ...item.logs.map((l) => l.id)) + 1,
          kind: 'confirmed',
          created_at: item.confirmed_at,
        });
        return json(item);
      },
      { action: true },
    ),
  ),
  http.post<IdParams>(
    `${API}/partner/orders/:id/date-change`,
    withSession<IdParams>(
      async ({ db, params, request }) => {
        const item = byId(db.partnerOrders, params.id);
        if (!item) return error(404, 'NOT_FOUND');
        if (item.status !== 'confirmed') return error(409, 'ORDER_NOT_CONFIRMED');
        const body = await readJson<Schemas['PartnerOrderDateChangeRequest']>(request);
        if (!body.requested_date || body.requested_date === item.expected_date) return error(422, 'VALIDATION_ERROR');
        item.date_change = {
          requested_date: body.requested_date,
          reason: body.reason?.trim() ?? '',
          requested_at: new Date().toISOString(),
        };
        return json(item);
      },
      { action: true },
    ),
  ),
  http.post<IdParams>(
    `${API}/partner/orders/:id/ship`,
    withSession<IdParams>(
      async ({ db, params, request }) => {
        const item = byId(db.partnerOrders, params.id);
        if (!item) return error(404, 'NOT_FOUND');
        if (item.status !== 'confirmed') return error(409, 'ORDER_NOT_CONFIRMED');
        const body = await readJson<Schemas['PartnerShipmentNoticeRequest']>(request);
        const doc = body.supplier_doc?.trim();
        if (!doc) return error(422, 'VALIDATION_ERROR');
        if (item.shipment_notices.some((row) => row.supplier_doc.toLowerCase() === doc.toLowerCase())) {
          return error(409, 'SHIPMENT_NOTICE_DUPLICATE');
        }
        item.shipment_notices.push({
          id: Math.max(8400, ...item.shipment_notices.map((row) => row.id)) + 1,
          supplier_doc: doc,
          carrier: body.carrier?.trim() ?? '',
          tracking_number: body.tracking_number?.trim() ?? '',
          note: body.note?.trim() ?? '',
          created_at: new Date().toISOString(),
        });
        return json(item);
      },
      { action: true },
    ),
  ),
  http.get(
    `${API}/partner/price-requests`,
    withSession(({ db, request }) => {
      const url = new URL(request.url);
      const status = url.searchParams.get('status');
      const q = url.searchParams.get('q')?.trim().toLowerCase() ?? '';
      const page = Math.max(1, Number(url.searchParams.get('page') ?? 1) || 1);
      const pageSize = Math.min(100, Math.max(1, Number(url.searchParams.get('page_size') ?? 20) || 20));
      if (status && !['sent', 'answered', 'failed'].includes(status)) {
        return error(422, 'VALIDATION_ERROR');
      }
      const searched = db.partnerPriceRequests.filter(
        (item) => !q || item.subject.toLowerCase().includes(q) || item.note.toLowerCase().includes(q),
      );
      const found = status ? searched.filter((item) => item.status === status) : searched;
      const items: Schemas['PartnerPriceRequestListItem'][] = found
        .slice((page - 1) * pageSize, page * pageSize)
        .map((row) => ({
          id: row.id,
          status: row.status,
          subject: row.subject,
          lines_count: row.lines.length,
          requested_at: row.requested_at,
          answered_at: row.answered_at,
        }));
      const body: Schemas['PartnerPriceRequestPage'] = {
        items,
        page,
        page_size: pageSize,
        total: found.length,
        counts: partner.rfqStatusCounts(searched),
      };
      return json(body);
    }),
  ),
  http.get<IdParams>(
    `${API}/partner/price-requests/:id`,
    withSession<IdParams>(({ db, params }) => {
      const item = byId(db.partnerPriceRequests, params.id);
      return item ? json(item) : error(404, 'NOT_FOUND');
    }),
  ),
  http.post<IdParams>(
    `${API}/partner/price-requests/:id/respond`,
    withSession<IdParams>(
      async ({ db, params, request }) => {
        const item = byId(db.partnerPriceRequests, params.id);
        if (!item) return error(404, 'NOT_FOUND');
        const body = await readJson<Schemas['PartnerPriceRequestResponse']>(request);
        if (item.status === 'failed') return error(409, 'REQUEST_NOT_SENT');
        if (item.status === 'answered') return error(409, 'ALREADY_ANSWERED');
        if (!body.answer_note?.trim()) return error(422, 'VALIDATION_ERROR');
        item.status = 'answered';
        item.answer_note = body.answer_note.trim();
        item.answer_currency = body.lines?.length ? (body.currency ?? null) : null;
        for (const row of body.lines ?? []) {
          const line = item.lines.find((candidate) => candidate.id === row.id);
          if (!line) return error(422, 'VALIDATION_ERROR');
          line.answer_price = row.unit_price;
        }
        item.answered_at = new Date().toISOString();
        return json(item);
      },
      { action: true },
    ),
  ),
  http.get(
    `${API}/partner/finance`,
    withSession(({ db, request }) => {
      const query = new URL(request.url).searchParams;
      return json(
        partner.partnerFinanceSummary(
          db.partnerOrders,
          Number(query.get('page') ?? 1),
          Number(query.get('page_size') ?? 20),
        ),
      );
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
