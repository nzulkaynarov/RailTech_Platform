import { http, HttpResponse, type JsonBodyType } from 'msw';

import type { Schemas } from '@/api/portal';
import { businessToday } from '@/lib/format';
import { crmFormHandlers, resetMockCrmForm } from './crmForm';
import * as fixtures from './fixtures';

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
 * КП с истёкшим сроком → 409 `QUOTE_EXPIRED`; повторное действие над закрытым объектом → 409 `*_FINALIZED`;
 * PDF документа `DOC_PREPARING_ONCE` первый раз отвечает 202 + `Retry-After`, `DOC_ALWAYS_PREPARING` — всегда 202.
 */
const API = '*/api/portal/v1';
const SESSION_KEY = 'cabinet.mock.session';

type Role = 'actor' | 'viewer';
type Dataset = 'demo' | 'empty';
interface MockSession {
  role: Role;
  auth_method: Schemas['Me']['auth_method'];
  /** `empty` — компания без запросов, КП, документов (пустые состояния экранов). */
  dataset?: Dataset;
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
    /** Сколько раз запрошен файл документа — для сценария «PDF готовится» (202 → 200). */
    fileRequests: new Map<number, number>(),
    /** КП, по которым клиент запросил код акцепта: id КП → выданный код. */
    quoteCodes: new Map<number, string>(),
    /** Загруженные файлы (`/uploads`): upload_id → имя; приёмка акта проверяет, что скан загружен. */
    uploads: new Map<string, string>(),
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

function me(session: MockSession): Schemas['Me'] {
  return { ...fixtures.meFor(contactFor(session.role), session.auth_method), company: dbOf(session).company };
}

function sessionFromToken(token: string, authMethod: MockSession['auth_method']): MockSession {
  return {
    role: token.includes('viewer') ? 'viewer' : 'actor',
    auth_method: authMethod,
    dataset: token.includes('empty') ? 'empty' : 'demo',
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

/** Элемент списка КП — карточка без строк и служебных полей (`deal` остаётся как есть). */
function quoteListItem(quote: Schemas['Quote']): Schemas['QuoteListItem'] {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { lines, public_url, pdf_document_id, rejected_reason, ...item } = quote;
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
    return new HttpResponse(null, { status: 200 });
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
  http.post(
    `${API}/auth/logout`,
    withSession(() => {
      setMockSession(null);
      return new HttpResponse(null, { status: 204 });
    }),
  ),
  http.get(`${API}/me`, withSession(({ session }) => json(me(session)))),

  // --- запросы ------------------------------------------------------------------------------
  http.get(`${API}/requests`, withSession(({ db }) => json(db.requests))),
  http.get<IdParams>(
    `${API}/requests/:id`,
    withSession<IdParams>(({ db, params }) => {
      const item = byId(db.requests, params.id);
      return item ? json(item) : error(404, 'NOT_FOUND');
    }),
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

  // --- договоры, счета, акты ------------------------------------------------------------------
  http.get(`${API}/contracts`, withSession(({ db }) => json(db.contracts))),
  http.post<IdParams>(
    `${API}/contracts/:id/sign`,
    withSession<IdParams>(
      ({ db, params }) => {
        const contract = byId(db.contracts, params.id);
        if (!contract) return error(404, 'NOT_FOUND');
        if (contract.status !== 'sent' && contract.status !== 'signed_by_company') return error(409, 'CONTRACT_FINALIZED');
        contract.status = contract.status === 'signed_by_company' ? 'signed' : 'signed_by_client';
        contract.signed_by_client_at = new Date().toISOString();
        return json(contract);
      },
      { action: true },
    ),
  ),
  http.get(`${API}/invoices`, withSession(({ db }) => json(db.invoices))),
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
      return json(
        db.documents.filter((doc) => (!kind || doc.kind === kind) && (!dealId || String(doc.deal?.id) === dealId)),
      );
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
        items: found.slice((page - 1) * pageSize, page * pageSize),
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

  // --- компания и команда -----------------------------------------------------------------------
  http.get(`${API}/company`, withSession(({ db }) => json(db.company))),
  http.put(
    `${API}/company`,
    withSession(
      async ({ db, request }) => {
        const body = await readJson<Schemas['CompanyUpdate']>(request);
        if (body.name !== undefined && !body.name.trim()) return error(422, 'VALIDATION_ERROR');
        if (body.inn !== undefined && body.inn !== '' && !/^\d{9,14}$/.test(body.inn)) return error(422, 'INN_INVALID');
        db.company = { ...db.company, ...body };
        return json(db.company);
      },
      { action: true },
    ),
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
  // Публичная форма CRM «Запрос» со страницы «Я новый клиент» (M2-CAB-03) — src/mocks/crmForm.ts.
  ...crmFormHandlers,
];
