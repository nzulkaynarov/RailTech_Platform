/**
 * Проход глазами + axe по экранам ERP на стенде ансамбля (FIX-58, D-06).
 *
 * Не тест CI: ходит в живой стенд через Vite dev-сервер с прокси на API стенда.
 *
 *   cd apps/erp/frontend
 *   VITE_DEV_PROXY_TARGET=http://erp.localhost:8088 npx vite --port 5158 --strictPort &
 *   AXE_PASSWORD=… node e2e/axe-stand.mjs --out ../../../docs/screens/fix-58 [--shots] [--only quote-builder]
 *
 * Вход — seed-сотрудник (роль «Руководитель», AXE_USER, по умолчанию aziz.kodirov@example.com), пароль — из
 * AXE_PASSWORD. Кадры «Наблюдатель» — тот же вход, но ответ /me подменён на пустой набор прав (интерфейс
 * видит только чтение; сервер при этом по-прежнему отвечает «Руководителю»: нужны только кадры UI).
 * Данные стенда не меняются: только чтение, диалоги открываются и закрываются без отправки.
 */
import { chromium } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs';
import path from 'node:path';

const args = process.argv.slice(2);
const opt = (name, def) => {
	const i = args.indexOf(`--${name}`);
	return i >= 0 ? args[i + 1] : def;
};
const OUT = path.resolve(opt('out', '../../../docs/screens/fix-58'));
const ONLY = opt('only', '');
const SHOTS = args.includes('--shots');
const SHOT_PREFIX = opt('shot-prefix', '');
const BASE = process.env.AXE_BASE || 'http://localhost:5158';
const STAND = process.env.AXE_STAND || 'http://erp.localhost:8088';
const USER = process.env.AXE_USER || 'aziz.kodirov@example.com';
const PASSWORD = process.env.AXE_PASSWORD;
if (!PASSWORD) throw new Error('AXE_PASSWORD не задан');
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];
const VIEWPORTS = [
	{ width: 1440, height: 900 },
	{ width: 390, height: 844 },
];

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// Кадры. `role`: head | viewer. `open` — действие после перехода (клик, диалог). `shot` — снимать ли PNG.
const FRAMES = [
	{ name: 'dashboard-head', hash: 'dashboard', role: 'head', shot: true },
	{ name: 'dashboard-viewer', hash: 'dashboard', role: 'viewer' },
	{ name: 'deals-list-head', hash: 'crm-deals', role: 'head', shot: true },
	{ name: 'deals-list-viewer', hash: 'crm-deals', role: 'viewer' },
	{ name: 'quotes-list-head', hash: 'crm-quotes', role: 'head', shot: true },
	{ name: 'clients-head', hash: 'clients', role: 'head' },
	{ name: 'contracts-head', hash: 'contracts', role: 'head', shot: true },
	{ name: 'contracts-viewer', hash: 'contracts', role: 'viewer' },
	{ name: 'contract-drawer-head', hash: 'contracts', role: 'head', open: 'row' },
	{ name: 'invoices-head', hash: 'invoices', role: 'head', shot: true },
	{ name: 'invoices-viewer', hash: 'invoices', role: 'viewer' },
	{ name: 'invoice-drawer-head', hash: 'invoices', role: 'head', open: 'row' },
	{ name: 'payments-head', hash: 'payments', role: 'head', shot: true },
	{ name: 'payments-viewer', hash: 'payments', role: 'viewer' },
	{ name: 'acts-head', hash: 'acts', role: 'head' },
	{ name: 'fulfillments-head', hash: 'fulfillments', role: 'head', shot: true },
	{ name: 'settings-team-head', hash: 'settings?section=team', role: 'head' },
	{ name: 'settings-viewer', hash: 'settings', role: 'viewer' },
	// Сделки и КП (id — сделки стенда: 24 принята, 17 черновик КП, 21 отправлено)
	{ name: 'request-detail-accepted-head', hash: 'request-detail/24', role: 'head', shot: true },
	{ name: 'request-detail-accepted-viewer', hash: 'request-detail/24', role: 'viewer', shot: true },
	{ name: 'request-detail-draft-head', hash: 'request-detail/17', role: 'head' },
	{ name: 'request-detail-sent-head', hash: 'request-detail/21', role: 'head' },
	{ name: 'quote-builder-draft-head', hash: 'deal-quote/17', role: 'head', shot: true },
	{ name: 'quote-builder-sent-head', hash: 'deal-quote/21', role: 'head', shot: true },
	{ name: 'quote-builder-accepted-head', hash: 'deal-quote/24', role: 'head', shot: true },
	{ name: 'quote-builder-viewer', hash: 'deal-quote/24', role: 'viewer', shot: true },
	{ name: 'quote-builder-charges-head', hash: 'deal-quote/17', role: 'head', open: 'charges-tab' },
	{ name: 'quote-send-dialog-head', hash: 'deal-quote/17', role: 'head', open: 'send-dialog' },
	// Тост «Ссылка скопирована» (sonner richColors) — раньше 4,25:1 (D-06)
	{ name: 'toast-success-head', hash: 'deal-quote/21', role: 'head', open: 'copy-link' },
];

function violationsOf(results, frame) {
	return results.violations.map((v) => ({
		screen: frame,
		id: v.id,
		impact: v.impact,
		help: v.help,
		nodes: v.nodes.length,
		target: v.nodes[0]?.target?.join(' ') ?? '',
		html: (v.nodes[0]?.html ?? '').slice(0, 220),
	}));
}

// Диалог отправки КП открывается только у КП «Готово к отправке» (после согласования). На стенде такого
// нет, а данные стенда менять нельзя — подменяем статус в ответе сделки (только в браузере, сервер не трогаем).
let readyToSendMode = false;
async function emulateReadyToSend(page) {
	await page.route(/\/crm\/deals\/17\/$/, async (route) => {
		const res = await route.fetch();
		const body = await res.json();
		if (readyToSendMode && body.active_quote) {
			body.active_quote.status_code = 'READY_TO_SEND';
			body.active_quote.status_name = 'Готово к отправке';
		}
		await route.fulfill({ response: res, json: body });
	});
}

async function login(page) {
	await page.goto(BASE + '/');
	await page.getByLabel(/e-?mail|почт/i).first().fill(USER);
	await page.locator('input[type="password"]').first().fill(PASSWORD);
	await page.locator('form button[type="submit"]').first().click();
	await page.waitForSelector('[data-sidebar="sidebar"], [data-slot="sidebar-inset"]', { timeout: 30_000 });
}

async function makeViewerPage(context) {
	// Свой контекст (своё localStorage и cookie): иначе «пустые» права попадают в сохранённого пользователя и
	// ломают соседнюю страницу «Руководителя» после перезагрузки.
	const page = await context.newPage();
	await page.route('**/accounts/users/me/', async (route) => {
		const res = await route.fetch();
		const body = await res.json();
		body.capabilities = { ...(body.capabilities || {}), permissions: [], roles: [], is_solo_team: false };
		await route.fulfill({ response: res, json: body });
	});
	await login(page);
	return page;
}

async function openAction(page, kind) {
	if (kind === 'row') {
		const row = page.locator('tbody tr:visible').first();
		if (await row.count()) await row.click();
		else await page.locator('div.flex-col.p-4:visible').first().click();
		await page.waitForSelector('[role="dialog"]', { timeout: 8000 });
	} else if (kind === 'charges-tab') {
		await page.locator('[role="tab"][id$="-trigger-charges"]').click();
	} else if (kind === 'copy-link') {
		await page.getByRole('button', { name: /Копировать ссылку/i }).first().click();
		await page.waitForSelector('[data-sonner-toast]', { timeout: 8000 });
	} else if (kind === 'send-dialog') {
		await page.getByRole('button', { name: /Отправить КП/i }).first().click();
		await page.waitForSelector('[role="dialog"]', { timeout: 8000 });
	}
	await wait(600);
}

async function runFrame(page, frame, viewport, all, unreachable, errors) {
	const label = `${frame.name}-${viewport.width}`;
	try {
		readyToSendMode = frame.open === 'send-dialog';
		if (readyToSendMode) {
			// Свежая загрузка приложения: иначе сделка 17 уже в кэше запросов с настоящим статусом.
			await page.goto(BASE + '/');
			await page.waitForSelector('[data-slot="sidebar-inset"]', { timeout: 30_000 });
		}
		await page.evaluate((h) => {
			window.location.hash = h;
		}, frame.hash);
		await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
		await wait(1200);
		if (frame.open) {
			try {
				await openAction(page, frame.open);
			} catch (e) {
				console.log('unreachable', label, String(e.message).split('\n')[0], page.url(), (await page.locator('button').allInnerTexts()).filter(Boolean).slice(-12));
				unreachable.push(label);
				return;
			}
		}
		const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
		all.push(...violationsOf(results, label));
		// Проход по текстам (D-12): сырые коды, «null», «undefined», «NaN» на экране.
		const raw = await page.evaluate(() =>
			(document.body.innerText.match(/\b[A-Z]{2,}(?:_[A-Z0-9]+)+\b|\[[A-Z_]+\]|\bnull\b|\bundefined\b|\bNaN\b/g) || []).slice(0, 10),
		);
		if (raw.length) rawTexts.push({ screen: label, found: [...new Set(raw)] });
		if (SHOTS && frame.shot) {
			await page.screenshot({ path: path.join(OUT, `${SHOT_PREFIX}${label}.png`) });
		}
		await page.keyboard.press('Escape').catch(() => {});
	} catch (e) {
		errors.push(`${label}: ${String(e.message).slice(0, 200)}`);
	}
}

async function publicQuoteFrames(browser, viewport, all, errors) {
	// Публичная страница КП (клиентский экран): токен берём из API под тем же сотрудником.
	const ctx = await browser.newContext({ viewport });
	try {
		const tokenRes = await ctx.request.post(`${STAND}/api/v1/auth/token/`, { data: { email: USER, password: PASSWORD } });
		const access = (await tokenRes.json()).access;
		const quote = await (await ctx.request.get(`${STAND}/api/v1/crm/quotes/20/`, { headers: { Authorization: `Bearer ${access}` } })).json();
		const page = await ctx.newPage();
		const url = process.env.AXE_PUBLIC_URL || `${STAND}/api/v1/public/quotes/${quote.public_access_token}/`;
		if (process.env.AXE_PUBLIC_PATCH) {
			// Стенд отдаёт СТАРЫЙ шаблон публичной страницы (бэкенд ERP на стенде не пересобирается). Чтобы
			// проверить новую раскраску до пересборки, берём HTML стенда и подставляем новое значение
			// переменной из правки шаблона (`quote_public_page.html`): `--muted` OLD=NEW.
			const [from, to] = process.env.AXE_PUBLIC_PATCH.split('=');
			const html = await (await ctx.request.get(url, { headers: { Accept: 'text/html' } })).text();
			await page.setContent(html.split(from).join(to));
		} else {
			await page.goto(url);
		}
		await wait(1000);
		const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
		all.push(...violationsOf(results, `public-quote-client-${viewport.width}`));
		if (SHOTS) await page.screenshot({ path: path.join(OUT, `${SHOT_PREFIX}public-quote-client-${viewport.width}.png`), fullPage: false });
	} catch (e) {
		errors.push(`public-quote-${viewport.width}: ${String(e.message).slice(0, 200)}`);
	} finally {
		await ctx.close();
	}
}

const browser = await chromium.launch();
const all = [];
const unreachable = [];
const errors = [];
const screens = [];
const rawTexts = [];
fs.mkdirSync(OUT, { recursive: true });

for (const viewport of VIEWPORTS) {
	const context = await browser.newContext({ viewport, locale: 'ru-RU', permissions: ['clipboard-read', 'clipboard-write'] });
	const head = await context.newPage();
	await login(head);
	await emulateReadyToSend(head);
	const viewerContext = await browser.newContext({ viewport, locale: 'ru-RU' });
	const viewer = await makeViewerPage(viewerContext);
	for (const frame of FRAMES) {
		if (ONLY && !frame.name.includes(ONLY)) continue;
		screens.push(`${frame.name}-${viewport.width}`);
		await runFrame(frame.role === 'viewer' ? viewer : head, frame, viewport, all, unreachable, errors);
	}
	await context.close();
	await viewerContext.close();
	if (!ONLY || 'public-quote'.includes(ONLY)) {
		screens.push(`public-quote-client-${viewport.width}`);
		await publicQuoteFrames(browser, viewport, all, errors);
	}
}
await browser.close();

const summary = {};
for (const v of all) summary[`${v.id}/${v.impact}`] = (summary[`${v.id}/${v.impact}`] || 0) + 1;
const outFile = path.join(OUT, opt('json', 'axe-results.json'));
fs.writeFileSync(
	outFile,
	JSON.stringify(
		{
			generated_by: 'apps/erp/frontend/e2e/axe-stand.mjs',
			tags: TAGS,
			screens,
			unreachable_dialogs: unreachable,
			errors,
			raw_texts: rawTexts,
			violations: all.map(({ html, ...rest }) => rest),
		},
		null,
		2,
	) + '\n',
);
fs.writeFileSync(outFile.replace(/\.json$/, '.debug.json'), JSON.stringify(all, null, 2));
const bad = all.filter((v) => v.impact === 'serious' || v.impact === 'critical');
console.log('frames:', screens.length, 'violations:', all.length, 'serious/critical:', bad.length);
console.log(summary);
if (unreachable.length) console.log('unreachable:', unreachable);
if (errors.length) console.log('errors:', errors);
if (rawTexts.length) console.log('raw texts:', JSON.stringify(rawTexts));
