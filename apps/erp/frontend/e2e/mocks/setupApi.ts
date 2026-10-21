import type { Page, Route } from '@playwright/test';

/**
 * Замоканный API ERP для мастера первого запуска (FIX-65) — без стенда и без Docker.
 * `role: 'admin'` — суперпользователь без компании; `'staff'` — сотрудник без компании.
 * Все значения фейковые. Неизвестный GET отвечает пустым списком.
 */
export interface SetupMockHandle {
	requests: string[];
	/** Тела POST `setup/company/`. */
	created: unknown[];
}

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

export async function mockSetupApi(page: Page, opts: { role: 'admin' | 'staff' }): Promise<SetupMockHandle> {
	const handle: SetupMockHandle = { requests: [], created: [] };
	const admin = opts.role === 'admin';
	let companyCreated = false;
	const baseUser = {
		id: 1, username: 'e2e', email: 'e2e@example.test', first_name: 'Тест', last_name: 'Тестов', phone: '',
		is_superuser: admin, is_active: true, preferences: { language: 'ru', theme: 'light' },
		capabilities: { permissions: admin ? ['settings.edit'] : [] },
	};
	const user = () =>
		companyCreated ? { ...baseUser, company: { id: 1, name: 'ООО Рейл', inn: '123456789', country: null, logo: null } } : baseUser;

	await page.addInitScript((u) => {
		localStorage.setItem('erp-auth', JSON.stringify({ state: { isAuthenticated: true, user: u }, version: 0 }));
		localStorage.setItem('i18nextLng', 'ru');
	}, baseUser);

	await page.route('**/api/v1/**', (route) => {
		const req = route.request();
		const path = new URL(req.url()).pathname.replace(/^.*\/api\/v1\//, '');
		handle.requests.push(`${req.method()} ${path}`);
		if (path === 'accounts/users/me/') return json(route, user());
		if (path === 'setup/status/') {
			return json(route, { setup_required: !companyCreated, can_setup: admin && !companyCreated });
		}
		if (path === 'setup/company/' && req.method() === 'POST') {
			const body = req.postDataJSON() as { inn?: string };
			handle.created.push(body);
			if (body.inn && !/^\d{9}$/.test(body.inn)) return json(route, { inn: ['Некорректный формат ИНН.'] }, 422);
			companyCreated = true;
			return json(route, { id: 1, name: 'ООО Рейл' }, 201);
		}
		if (req.method() !== 'GET') return json(route, {});
		return json(route, { count: 0, next: null, previous: null, results: [] });
	});
	return handle;
}
