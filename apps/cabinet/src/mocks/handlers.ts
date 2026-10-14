import { http, HttpResponse, type JsonBodyType } from 'msw';

import type { Schemas } from '@/api/portal';
import { businessToday } from '@/lib/format';
import { crmFormHandlers, resetMockCrmForm } from './crmForm';
import * as fixtures from './fixtures';

/**
 * Мок портального API на MSW — граница HTTP для dev (`VITE_PORTAL_MOCK=1`) и тестов.
 * Поведение — по `erp-portal.yaml`: без сессии 401, `can_act=false` → 403 на действиях,
 * чужое/несуществующее → 404, ошибки `{"detail": CODE}`. До M2-ERP-01 коды ошибок — предположение
 * Cabinet (UNAUTHORIZED, INVALID_INIT_DATA, MAGIC_LINK_EXPIRED, QUOTE_CODE_INVALID…), ERP их подтвердит в контракте.
 *
 * Сценарии входа:
 * - `POST /auth/telegram` — любой `init_data`; содержит `bad` → 401, `viewer` → контакт без права действовать,
 *   `empty` → компания без объектов;
 * - `GET /auth/magic/{token}` — `expired` → 410, `viewer` → без права действовать, `empty` → пустая компания,
 *   иное → основной контакт.
 *
 * Сценарии разделов (M2-CAB-02): код акцепта КП — `MOCK_ACCEPT_CODE`, иной → 409 `QUOTE_CODE_INVALID`;
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

function quoteListItem(quote: Schemas['Quote']): Schemas['QuoteListItem'] {
  const { id, deal_id, number, version, status, total, valid_until, sent_at } = quote;
  return { id, deal_id, number, version, status, total, valid_until, sent_at };
}

async function readJson<T>(request: Request): Promise<Partial<T>> {
  try {
    return ((await request.json()) ?? {}) as Partial<T>;
  } catch {
    return {};
  }
}

const QUANTITY_RE = /^\d+(\.\d+)?$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function validRequestBody(body: Partial<Schemas['ClientRequestCreate']>): body is Schemas['ClientRequestCreate'] {
  if (!body.summary?.trim() || body.summary.length > 5000 || !Array.isArray(body.lines)) return false;
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
    return new HttpResponse(null, { status: 200 });
  }),
  http.get<IdParams & { token: string }>(`${API}/auth/magic/:token`, ({ params }) => {
    if (params.token === 'expired') return error(410, 'MAGIC_LINK_EXPIRED');
    const session = sessionFromToken(params.token, 'magic_link');
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
          deal_id: null,
          created_at: new Date().toISOString(),
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
    `${API}/quotes/:id/accept`,
    withSession<IdParams>(
      async ({ db, params, request }) => {
        const quote = byId(db.quotes, params.id);
        if (!quote) return error(404, 'NOT_FOUND');
        const { code } = await readJson<{ code: string }>(request);
        if (quote.status !== 'sent' && quote.status !== 'viewed') return error(409, 'QUOTE_FINALIZED');
        if (quote.valid_until && quote.valid_until < businessToday()) return error(409, 'QUOTE_EXPIRED');
        if (!code || code.length < 4 || code.length > 12) return error(422, 'VALIDATION_ERROR');
        if (code !== fixtures.MOCK_ACCEPT_CODE) return error(409, 'QUOTE_CODE_INVALID');
        quote.status = 'accepted';
        // ERP создаёт договор сам (BUSINESS §4, шаг 6) — без файла, пока PDF не отрендерен.
        if (quote.deal_id !== undefined && !db.contracts.some((item) => item.deal_id === quote.deal_id)) {
          db.contracts = [
            {
              id: 400 + quote.deal_id,
              deal_id: quote.deal_id,
              number: `D-2026-${String(quote.deal_id).padStart(4, '0')}`,
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
      ({ db, params }) => {
        const act = byId(db.acts, params.id);
        if (!act) return error(404, 'NOT_FOUND');
        if (act.status !== 'issued') return error(409, 'ACT_FINALIZED');
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
  http.get(
    `${API}/documents`,
    withSession(({ db, request }) => {
      const url = new URL(request.url);
      const kind = url.searchParams.get('kind');
      const dealId = url.searchParams.get('deal_id');
      return json(
        db.documents.filter((doc) => (!kind || doc.kind === kind) && (!dealId || String(doc.deal_id) === dealId)),
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

  // --- каталог ----------------------------------------------------------------------------------
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
