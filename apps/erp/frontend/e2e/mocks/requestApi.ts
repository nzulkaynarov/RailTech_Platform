import type { Page, Route } from '@playwright/test';

/**
 * FIX-67 — замоканный API ERP для карточки заявки (`#request-detail/<id>`) и конструктора КП
 * (`#deal-quote/<id>`): без стенда и Docker. Все значения фейковые, префикс `FIX67`.
 * Неизвестный GET отвечает пустым списком, чтобы виджеты оболочки не падали.
 */
export const DEAL_ID = 67;
export const QUOTE_ID = 670;

export interface RequestMock {
	/** Коды прав из `/me`. */
	permissions: string[];
	/** Стадия сделки (`stage_code`). */
	stage?: string;
	/** Сколько строк в заявке клиента. */
	requestLines?: number;
	/** Текст заявки (заявка словами). */
	text?: string;
	/** Есть ли пустой черновик КП продавца (конструктор КП). */
	withDraftQuote?: boolean;
}

export interface MockHandle {
	/** Тела POST-запросов к API: `path → [body]`. */
	posts: Record<string, unknown[]>;
}

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

function draftQuote() {
	return {
		id: QUOTE_ID, deal: DEAL_ID, version: 1, status: 1, status_code: 'DRAFT', status_name: 'Черновик',
		quote_currency: 'UZS', cost_currency_default: 'UZS', vat_rate: '12', margin_percent: '20',
		fx_snapshot: {}, fx_manual: {}, fx_market: {}, items: [], charges: [], approval_steps: [],
		subtotal_excl_vat: '0', charges_total: '0', vat_amount: '0', total_incl_vat: '0', frozen_at: null,
		economics: null, created_at: '2026-10-21T08:00:00Z',
	};
}

export async function mockRequestApi(page: Page, opts: RequestMock): Promise<MockHandle> {
	const handle: MockHandle = { posts: {} };
	const lines = opts.requestLines ?? 0;
	const user = {
		id: 1, username: 'e2e', email: 'e2e@example.test', first_name: 'Тест', last_name: 'Тестов', phone: '',
		is_superuser: false, is_active: true, preferences: { language: 'ru', theme: 'light' },
		company: { id: 1, name: 'ООО Тест', inn: '000000000', country: 1, logo: null },
		capabilities: { permissions: opts.permissions },
	};
	await page.addInitScript((u) => {
		localStorage.setItem('erp-auth', JSON.stringify({ state: { isAuthenticated: true, user: u }, version: 0 }));
		localStorage.setItem('i18nextLng', 'ru');
	}, user);

	await page.route('**/api/v1/**', (route) => {
		const req = route.request();
		const path = new URL(req.url()).pathname.replace(/^.*\/api\/v1\//, '');
		if (req.method() !== 'GET') {
			(handle.posts[path] ??= []).push(req.postDataJSON());
			return json(route, {});
		}
		if (path === 'accounts/users/me/') return json(route, user);
		if (path === `crm/deals/${DEAL_ID}/`) {
			return json(route, {
				id: DEAL_ID, title: opts.text ? 'FIX67 Заявка: ООО Пример' : 'FIX67 Запрос из Cabinet',
				company_name: 'ООО Пример', stage: opts.stage ?? 'SOURCING', stage_code: opts.stage ?? 'SOURCING',
				stage_name: 'Подбор поставщиков', notes: opts.text ?? '', request_text: opts.text ?? '',
				request_lines_count: lines, assigned_to: null, viewer_can_release: false,
				active_quote: opts.withDraftQuote ? draftQuote() : null,
				quotes: opts.withDraftQuote ? [draftQuote()] : [], created_at: '2026-10-21T08:00:00Z',
			});
		}
		if (path === `crm/deals/${DEAL_ID}/documents/`) {
			return json(route, { contract: null, invoices: [], payments: [], acts: [], fulfillment: null, next_step: null });
		}
		if (path === 'crm/quote-items/' || path === 'crm/document-templates/' || path === 'crm/generated-documents/' || path === 'crm/timeline/') {
			return json(route, []);
		}
		if (path === `crm/quotes/${QUOTE_ID}/approval-preview/`) {
			return json(route, { would_auto_approve: false, below_floor: false, steps: [] });
		}
		if (path.startsWith('master-data/currencies')) {
			return json(route, [{ id: 1, code: 'UZS', name: 'Сум' }, { id: 2, code: 'USD', name: 'Доллар' }]);
		}
		return json(route, { count: 0, next: null, previous: null, results: [] });
	});
	return handle;
}
