import type { Page, Route } from '@playwright/test';

/**
 * Замоканный API ERP для Settings Hub (`/?section=<ключ>#settings`) — без стенда и без Docker (FIX-42).
 * Все значения фейковые. Неизвестный GET отвечает пустым списком, чтобы остальные виджеты оболочки не падали.
 */
export interface SettingsMockHandle {
	/** Запросы к API по порядку: `METHOD path`. */
	requests: string[];
	/** Тела PATCH к `system-settings/`. */
	systemSettingsPatches: unknown[];
}

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

const page_ = (results: unknown[]) => ({ count: results.length, next: null, previous: null, results });

const CATEGORIES = [
	{ id: 1, name: 'Запчасти', parent: null, domain_type: 1, sort_order: 10, is_active: true },
	{ id: 2, name: 'Подшипники', parent: 1, domain_type: 1, sort_order: 10, is_active: true },
	{ id: 3, name: 'Роликовые подшипники', parent: 2, domain_type: 1, sort_order: 10, is_active: true },
	{ id: 4, name: 'Услуги', parent: null, domain_type: 2, sort_order: 20, is_active: true },
];

export async function mockSettingsApi(page: Page): Promise<SettingsMockHandle> {
	const handle: SettingsMockHandle = { requests: [], systemSettingsPatches: [] };
	const user = {
		id: 1, username: 'e2e', email: 'e2e@example.test', first_name: 'Тест', last_name: 'Тестов', phone: '',
		is_superuser: true, is_active: true, preferences: { language: 'ru', theme: 'light' },
		company: { id: 1, name: 'ООО Тест', inn: '000000000', country: 1, logo: null },
		capabilities: { permissions: ['settings.edit', 'catalog.manage', 'team.manage', 'settings.charge_templates'] },
	};

	await page.addInitScript((u) => {
		localStorage.setItem('erp-auth', JSON.stringify({ state: { isAuthenticated: true, user: u }, version: 0 }));
		localStorage.setItem('i18nextLng', 'ru');
	}, user);

	await page.route('**/api/v1/**', (route) => {
		const req = route.request();
		const path = new URL(req.url()).pathname.replace(/^.*\/api\/v1\//, '');
		handle.requests.push(`${req.method()} ${path}`);
		if (path === 'accounts/users/me/') return json(route, user);
		if (path === 'system-settings/') {
			if (req.method() === 'PATCH') {
				handle.systemSettingsPatches.push(req.postDataJSON());
				return json(route, {});
			}
			return json(route, {
				vat_rate: '12.00', exchange_rate_usd_uzs: '12650.0000', platform_name: 'RailTech ERP',
				support_email: 'support@example.test', logo_url: 'https://cdn.example.test/logo.png',
				domain: 'erp.example.test', crm_frontend_url: 'https://crm.example.test',
				maintenance_mode: false, is_two_factor_required: false, updated_at: '2026-10-20T10:00:00Z',
			});
		}
		if (req.method() !== 'GET') return json(route, {});
		if (path.startsWith('catalog/categories')) return json(route, page_(CATEGORIES));
		if (path.startsWith('catalog/domain-types')) return json(route, [{ id: 1, name: 'Товары' }, { id: 2, name: 'Услуги' }]);
		if (path === 'accounts/companies/1/settings/') {
			return json(route, {
				id: 1, company: 1, default_vat_rate: '12.00', default_margin_percent: '15.00', min_margin_percent: '10.00',
				target_margin_percent: '20.00', default_offer_validity_days: 14, payment_terms_days: 14,
				default_payment_terms: '', default_warranty_months: 12, fx_rate_max_age_days: 7,
				notify_client_on_schedule_shift: true,
			});
		}
		if (path.startsWith('master-data/')) return json(route, []);
		return json(route, page_([]));
	});
	return handle;
}
