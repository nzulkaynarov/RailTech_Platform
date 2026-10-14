import { http, HttpResponse, type JsonBodyType } from 'msw';

import type { Schemas } from '@/api/portal';
import * as fixtures from './fixtures';

/**
 * Мок портального API на MSW — граница HTTP для dev (`VITE_PORTAL_MOCK=1`) и тестов.
 * Поведение — по `erp-portal.yaml`: без сессии 401, `can_act=false` → 403 на действиях,
 * чужое/несуществующее → 404, ошибки `{"detail": CODE}`. До M2-ERP-01 коды ошибок — предположение
 * Cabinet (UNAUTHORIZED, INVALID_INIT_DATA, MAGIC_LINK_EXPIRED…), ERP их подтвердит в контракте.
 *
 * Сценарии входа:
 * - `POST /auth/telegram` — любой `init_data`; содержит `bad` → 401, содержит `viewer` → контакт без права действовать;
 * - `GET /auth/magic/{token}` — `expired` → 410, `viewer` → контакт без права действовать, иное → основной контакт.
 */
const API = '*/api/portal/v1';
const SESSION_KEY = 'cabinet.mock.session';

type Role = 'actor' | 'viewer';
interface MockSession {
  role: Role;
  auth_method: Schemas['Me']['auth_method'];
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

function createDb() {
  return {
    requests: structuredClone(fixtures.requests),
    quotes: structuredClone(fixtures.quotes),
    contracts: structuredClone(fixtures.contracts),
    acts: structuredClone(fixtures.acts),
    company: structuredClone(fixtures.company),
    team: structuredClone(fixtures.team),
  };
}

let db = createDb();

/** Для тестов: чистая сессия и данные фикстур. */
export function resetMockPortal(): void {
  setMockSession(null);
  db = createDb();
}

function contactFor(role: Role): Schemas['TeamMember'] {
  return role === 'viewer' ? fixtures.contactViewer : fixtures.contactActor;
}

function me(session: MockSession): Schemas['Me'] {
  return { ...fixtures.meFor(contactFor(session.role), session.auth_method), company: db.company };
}

function error(status: number, detail: string) {
  return HttpResponse.json({ detail } satisfies Schemas['Error'], { status });
}

function json<T extends JsonBodyType>(body: T, status = 200) {
  return HttpResponse.json(body, { status });
}

/** Обёртка эндпоинта с сессией: без неё 401, для действий без `can_act` — 403. */
function withSession<P>(
  resolver: (args: { session: MockSession; params: P; request: Request }) => Response | Promise<Response>,
  { action = false }: { action?: boolean } = {},
) {
  return ({ params, request }: { params: P; request: Request }) => {
    const session = readSession();
    if (!session) return error(401, 'UNAUTHORIZED');
    if (action && !contactFor(session.role).can_act) return error(403, 'FORBIDDEN');
    return resolver({ session, params, request });
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

export const handlers = [
  // --- auth -----------------------------------------------------------------------------
  http.post(`${API}/auth/telegram`, async ({ request }) => {
    const body = (await request.json()) as { init_data?: string };
    const initData = body.init_data ?? '';
    if (!initData || initData.includes('bad')) return error(401, 'INVALID_INIT_DATA');
    const session: MockSession = { role: initData.includes('viewer') ? 'viewer' : 'actor', auth_method: 'telegram' };
    setMockSession(session);
    return json(me(session));
  }),
  http.post(`${API}/auth/magic-link`, async ({ request }) => {
    const body = (await request.json()) as { email?: string };
    if (!body.email || !body.email.includes('@')) return error(422, 'VALIDATION_ERROR');
    return new HttpResponse(null, { status: 200 });
  }),
  http.get<IdParams & { token: string }>(`${API}/auth/magic/:token`, ({ params }) => {
    if (params.token === 'expired') return error(410, 'MAGIC_LINK_EXPIRED');
    const session: MockSession = { role: params.token === 'viewer' ? 'viewer' : 'actor', auth_method: 'magic_link' };
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
  http.get(`${API}/requests`, withSession(() => json(db.requests))),
  http.post(
    `${API}/requests`,
    withSession(
      async ({ request }) => {
        const body = (await request.json()) as Schemas['ClientRequestCreate'];
        if (!body.summary?.trim() || !Array.isArray(body.lines)) return error(422, 'VALIDATION_ERROR');
        const created: Schemas['ClientRequest'] = {
          id: 500 + db.requests.length + 10,
          number: `Z-2026-${String(100 + db.requests.length).padStart(4, '0')}`,
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
  http.get(`${API}/quotes`, withSession(() => json(db.quotes.map(quoteListItem)))),
  http.get<IdParams>(
    `${API}/quotes/:id`,
    withSession<IdParams>(({ params }) => {
      const quote = byId(db.quotes, params.id);
      return quote ? json(quote) : error(404, 'NOT_FOUND');
    }),
  ),
  http.post<IdParams>(
    `${API}/quotes/:id/accept`,
    withSession<IdParams>(
      async ({ params, request }) => {
        const quote = byId(db.quotes, params.id);
        if (!quote) return error(404, 'NOT_FOUND');
        const { code } = (await request.json()) as { code?: string };
        if (quote.status !== 'sent' && quote.status !== 'viewed') return error(409, 'QUOTE_FINALIZED');
        if (!code || code.length < 4) return error(409, 'QUOTE_CODE_INVALID');
        quote.status = 'accepted';
        return json(quote);
      },
      { action: true },
    ),
  ),
  http.post<IdParams>(
    `${API}/quotes/:id/reject`,
    withSession<IdParams>(
      async ({ params, request }) => {
        const quote = byId(db.quotes, params.id);
        if (!quote) return error(404, 'NOT_FOUND');
        if (quote.status !== 'sent' && quote.status !== 'viewed') return error(409, 'QUOTE_FINALIZED');
        const { reason } = (await request.json()) as Schemas['Reason'];
        quote.status = 'rejected';
        quote.rejected_reason = reason;
        return json(quote);
      },
      { action: true },
    ),
  ),

  // --- договоры, счета, акты ------------------------------------------------------------------
  http.get(`${API}/contracts`, withSession(() => json(db.contracts))),
  http.post<IdParams>(
    `${API}/contracts/:id/sign`,
    withSession<IdParams>(
      ({ params }) => {
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
  http.get(`${API}/invoices`, withSession(() => json(fixtures.invoices))),
  http.get(`${API}/acts`, withSession(() => json(db.acts))),
  http.post<IdParams>(
    `${API}/acts/:id/accept`,
    withSession<IdParams>(
      ({ params }) => {
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
      async ({ params, request }) => {
        const act = byId(db.acts, params.id);
        if (!act) return error(404, 'NOT_FOUND');
        if (act.status !== 'issued') return error(409, 'ACT_FINALIZED');
        const { reason } = (await request.json()) as Schemas['Reason'];
        act.status = 'returned';
        act.returned_reason = reason;
        return json(act);
      },
      { action: true },
    ),
  ),

  // --- поставки и документы -------------------------------------------------------------------
  http.get(`${API}/deliveries`, withSession(() => json(fixtures.deliveries))),
  http.get(
    `${API}/documents`,
    withSession(({ request }) => {
      const url = new URL(request.url);
      const kind = url.searchParams.get('kind');
      const dealId = url.searchParams.get('deal_id');
      return json(
        fixtures.documents.filter(
          (doc) => (!kind || doc.kind === kind) && (!dealId || String(doc.deal_id) === dealId),
        ),
      );
    }),
  ),
  http.get<IdParams>(
    `${API}/documents/:id/file`,
    withSession<IdParams>(({ params }) => {
      const doc = byId(fixtures.documents, params.id);
      if (!doc) return error(404, 'NOT_FOUND');
      return new HttpResponse('%PDF-1.4\n% mock\n', {
        headers: {
          'Content-Type': 'application/pdf',
          'Content-Disposition': `attachment; filename="${doc.file_name ?? `${doc.number}.pdf`}"`,
        },
      });
    }),
  ),

  // --- каталог ----------------------------------------------------------------------------------
  http.get(
    `${API}/catalog`,
    withSession(({ request }) => {
      const url = new URL(request.url);
      const q = url.searchParams.get('q')?.toLowerCase() ?? '';
      const page = Math.max(1, Number(url.searchParams.get('page') ?? 1));
      const pageSize = Math.min(100, Math.max(1, Number(url.searchParams.get('page_size') ?? 20)));
      const found = fixtures.catalog.filter((item) => !q || item.name.toLowerCase().includes(q));
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
    withSession<IdParams>(({ params }) => {
      const item = byId(fixtures.catalog, params.id);
      return item ? json(item) : error(404, 'NOT_FOUND');
    }),
  ),

  // --- компания и команда -----------------------------------------------------------------------
  http.get(`${API}/company`, withSession(() => json(db.company))),
  http.put(
    `${API}/company`,
    withSession(
      async ({ request }) => {
        const body = (await request.json()) as Schemas['CompanyUpdate'];
        db.company = { ...db.company, ...body };
        return json(db.company);
      },
      { action: true },
    ),
  ),
  http.get(`${API}/team`, withSession(() => json(db.team))),
  http.post(
    `${API}/team/invite`,
    withSession(
      async ({ request }) => {
        const body = (await request.json()) as Schemas['TeamInvite'];
        if (!body.name?.trim() || !body.channels?.length) return error(422, 'VALIDATION_ERROR');
        const member: Schemas['TeamMember'] = {
          id: 100 + db.team.length + 10,
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
];
