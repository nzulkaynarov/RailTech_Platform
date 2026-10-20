import type { Page, Route } from '@playwright/test';

/**
 * Замоканный API ERP для экрана КП (`#deal-quote/<id>`) — без стенда и без Docker (FIX-44).
 * Все значения фейковые. Неизвестный запрос GET отвечает пустым списком, чтобы остальные
 * виджеты оболочки не падали; список таких запросов возвращается для диагностики.
 */
export const DEAL_ID = 42;
export const QUOTE_ID = 100;

export interface MockOptions {
	/** Коды прав из `/me` (`capabilities.permissions`). */
	permissions: string[];
	/** Сколько позиций в КП (выше порога виртуализации — окно строк). */
	itemCount?: number;
}

export interface MockHandle {
	/** Запросы, которые ушли к API, в порядке отправки: `METHOD path`. */
	requests: string[];
}

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

function makeQuote() {
	return {
		id: QUOTE_ID, deal: DEAL_ID, version: 1, status: 1, status_code: 'DRAFT', status_name: 'Черновик',
		quote_currency: 'UZS', cost_currency_default: 'UZS', vat_rate: '12', margin_percent: '20',
		fx_snapshot: {}, fx_manual: {}, fx_market: {}, items: [], charges: [], approval_steps: [],
		subtotal_excl_vat: '1000', charges_total: '0', vat_amount: '120', total_incl_vat: '1120',
		frozen_at: null,
		economics: {
			total_landed_cost: '800', gross_profit: '200', gross_margin_percent: '20',
			markup_percent: '25', charge_cost_total: '0', operating_profit: '200',
			below_cost: false, below_floor: false, min_margin_percent: '15',
			target_margin_percent: '25', fx_missing: [],
		},
		created_at: '2026-07-01T00:00:00Z',
	};
}

function makeItem(id: number) {
	return {
		id, quote: QUOTE_ID, imported_raw_name: `Тестовая позиция ${id}`, quantity: 1,
		frozen_base_price: '100', frozen_currency: 'UZS', logistics_cost: '0', customs_duty: '0',
		margin_percent: '0', discount_percent: '0', lead_time_days: 0,
		landed_cost: '100', final_price_excl_vat: '120', display_type: 'ITEM',
	};
}

export async function mockQuoteBuilderApi(page: Page, opts: MockOptions): Promise<MockHandle> {
	const handle: MockHandle = { requests: [] };
	const items = Array.from({ length: opts.itemCount ?? 8 }, (_, i) => makeItem(i + 1));
	const user = {
		id: 1, username: 'e2e', email: 'e2e@example.test', first_name: 'Тест', last_name: 'Тестов', phone: '',
		is_superuser: false, is_active: true, preferences: { language: 'ru', theme: 'light' },
		company: { id: 1, name: 'ООО Тест', inn: '000000000', country: 1, logo: null },
		capabilities: { permissions: opts.permissions },
	};

	// Оболочка рисуется сразу из сохранённой сессии; access-токен живёт только в памяти.
	await page.addInitScript((u) => {
		localStorage.setItem('erp-auth', JSON.stringify({ state: { isAuthenticated: true, user: u }, version: 0 }));
		localStorage.setItem('i18nextLng', 'ru');
	}, user);

	await page.route('**/api/v1/**', (route) => {
		const req = route.request();
		const url = new URL(req.url());
		const path = url.pathname.replace(/^.*\/api\/v1\//, '');
		handle.requests.push(`${req.method()} ${path}`);
		if (req.method() !== 'GET') return json(route, {});
		if (path === 'accounts/users/me/') return json(route, user);
		if (path === `crm/deals/${DEAL_ID}/`) {
			return json(route, {
				id: DEAL_ID, title: 'Тестовая сделка', stage: 'QUOTING', stage_code: 'QUOTING', notes: 'Нужны позиции из заявки клиента',
				active_quote: makeQuote(), created_at: '2026-07-01T00:00:00Z',
			});
		}
		if (path === 'crm/quote-items/') return json(route, items);
		if (path === `crm/quotes/${QUOTE_ID}/approval-preview/`) {
			// Как бэкенд у роли без quote.build: 403 + код права.
			if (!opts.permissions.includes('quote.build')) {
				return json(route, { detail: 'You do not have permission to perform this action.', code: 'permission_denied' }, 403);
			}
			return json(route, { would_auto_approve: false, below_floor: false, steps: [] });
		}
		if (path.startsWith('master-data/currencies')) {
			return json(route, [{ id: 1, code: 'UZS', name: 'Сум' }, { id: 2, code: 'USD', name: 'Доллар' }]);
		}
		// Всё остальное: пустой пагинированный список (виджеты оболочки, уведомления, настройки).
		return json(route, { count: 0, next: null, previous: null, results: [] });
	});
	return handle;
}
