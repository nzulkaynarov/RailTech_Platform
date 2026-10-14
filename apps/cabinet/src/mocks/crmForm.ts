import { http, HttpResponse } from 'msw';

import type { WebFormToken, WebLeadAccepted, WebLeadIn } from '@/api/crm';

/**
 * Мок публичной формы CRM «Запрос» (`/api/v1/leads/web*`, M3-CRM-05) — для `make dev` и тестов.
 * Поведение — как у CRM: honeypot `website` → 202 `{lead_id: null}`; без `consent: true` → 422
 * `consent_required`; без телефона и e-mail → `contact_required`; телефон короче 9 цифр →
 * `invalid_phone`; неизвестный токен → `form_token_invalid`. Ошибки — формат CRM (ADR-0017 CRM):
 * `{"code", "message", "details": {"reason", "field"}}`.
 *
 * Сценарии по тексту запроса (для проверки глазами): `#expired` — первая отправка получает
 * `form_token_expired` (форма тихо берёт новый токен и повторяет), `#fast` — `form_too_fast`,
 * `#limit` — 429 `rate_limited`.
 */
const API = '*/api/v1/leads/web';
/** У CRM по умолчанию 3 с; в моке — 1 с, чтобы повтор с новым токеном не тянул тесты. */
export const MOCK_MIN_FILL_SECONDS = 1;

let state = createState();

function createState() {
  return {
    issued: new Set<string>(),
    expiredOnce: false,
    nextLeadId: 1001,
    tokenRequests: 0,
    submissions: [] as WebLeadIn[],
  };
}

export function resetMockCrmForm(): void {
  state = createState();
}

/** Для тестов: что ушло в CRM и сколько раз брали токен. */
export function mockCrmForm(): { submissions: WebLeadIn[]; tokenRequests: number } {
  return { submissions: state.submissions, tokenRequests: state.tokenRequests };
}

function crmError(status: number, code: string, reason: string, field: string | null = null) {
  const details = field ? { reason, field } : { reason };
  return HttpResponse.json({ code, message: reason, details }, { status });
}

const invalid = (reason: string, field: string | null) => crmError(422, 'validation_failed', reason, field);

export const crmFormHandlers = [
  http.get(`${API}/token`, () => {
    state.tokenRequests += 1;
    const token = `mock-form-${state.tokenRequests}`;
    state.issued.add(token);
    const body: WebFormToken = {
      token,
      expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
      min_fill_seconds: MOCK_MIN_FILL_SECONDS,
    };
    return HttpResponse.json(body);
  }),

  http.post(API, async ({ request }) => {
    const body = (await request.json()) as WebLeadIn;
    state.submissions.push(body);
    if (body.website?.trim()) return HttpResponse.json({ lead_id: null } satisfies WebLeadAccepted, { status: 202 });
    if (body.consent !== true) return invalid('consent_required', 'consent');
    if (!state.issued.has(body.form_token)) return invalid('form_token_invalid', 'form_token');
    const text = body.text ?? '';
    if (text.includes('#expired') && !state.expiredOnce) {
      state.expiredOnce = true;
      return invalid('form_token_expired', 'form_token');
    }
    if (text.includes('#fast')) return invalid('form_too_fast', 'form_token');
    if (text.includes('#limit')) return crmError(429, 'rate_limited', 'rate_limited');
    const phone = body.phone?.trim() ?? '';
    if (!phone && !body.email?.trim()) return invalid('contact_required', 'phone');
    if (phone && phone.replace(/\D/g, '').length < 9) return invalid('invalid_phone', 'phone');
    const accepted: WebLeadAccepted = { lead_id: state.nextLeadId };
    state.nextLeadId += 1;
    return HttpResponse.json(accepted, { status: 202 });
  }),
];
