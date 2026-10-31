/**
 * CAB-FIX-2, CAB-FIX-3 · все экраны кабинета на dev-сборке с моком портального API (MSW), без стенда:
 * `npm run test:e2e:screens`.
 *
 * Роли actor (право действовать) и viewer (только просмотр) × 1440 и 390 px: на каждом экране axe (serious/critical = 0)
 * и отсутствие горизонтальной прокрутки (`snap`, как в гейте M2); сводка — `axe-summary.json` в E2E_SCREENS_DIR.
 * Снимки — ключевых экранов (запросы, проект, КП, счета на 1440/1280/390, компания с баром, сайдбар развёрнут и
 * свёрнут), uz и en, тема Mini App (стандартные светлая и тёмная themeParams Telegram — SDK подменён заглушкой, вход
 * через `POST /auth/telegram` мока). Скачки (CAB-FIX-3): CLS загрузки «Запросов» (10 прогонов на 1440 и 390), ввода
 * в «Компанию» и ⌘\ — `layout-shift` браузера. «Сегодня» — день фикстур мока (2026-10-14), как в vitest.
 */
import fs from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { SCREENS_DIR } from './helpers/env';
import { snap } from './helpers/shots';

type Role = 'actor' | 'viewer';

/** «Сегодня» фикстур мока: сроки КП и просрочка счетов как в vitest (src/test/setup.ts); таймеры настоящие. */
const FIXTURE_NOW = new Date('2026-10-14T12:00:00+05:00');

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(FIXTURE_NOW);
  // Сдвиги раскладки (Layout Instability API) — с самого начала загрузки страницы
  await page.addInitScript(() => {
    const store = window as unknown as { __shifts: Array<{ value: number; input: boolean; time: number }> };
    store.__shifts = [];
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries() as Array<PerformanceEntry & { value: number; hadRecentInput: boolean }>) {
        store.__shifts.push({ value: entry.value, input: entry.hadRecentInput, time: entry.startTime });
      }
    }).observe({ type: 'layout-shift', buffered: true });
  });
});

/** Сдвиги с момента `since` (мс от начала страницы): сумма (CLS этого шага) и число кадров со сдвигом. */
async function shiftsSince(page: Page, since = 0, withInput = true): Promise<{ cls: number; frames: number }> {
  const shifts = await page.evaluate(() => (window as unknown as { __shifts: Array<{ value: number; input: boolean; time: number }> }).__shifts);
  const counted = shifts.filter((shift) => shift.time >= since && (withInput || !shift.input) && shift.value > 0);
  return { cls: Number(counted.reduce((sum, shift) => sum + shift.value, 0).toFixed(4)), frames: counted.length };
}

const pageTime = (page: Page) => page.evaluate(() => performance.now());

/** Итог замеров CLS — в E2E_SCREENS_DIR/cls-summary.json (таблица «было / стало» в описании PR). */
function writeCls(entry: { action: string; width: number; runs: number[]; frames?: number }) {
  const file = path.join(SCREENS_DIR, 'cls-summary.json');
  let all: Array<{ action: string; width: number }>;
  try {
    all = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    all = [];
  }
  all = all.filter((row) => !(row.action === entry.action && row.width === entry.width));
  all.push({ ...entry, max: Math.max(...entry.runs) } as typeof all[number]);
  fs.mkdirSync(SCREENS_DIR, { recursive: true });
  fs.writeFileSync(file, `${JSON.stringify(all, null, 2)}\n`);
}

/** Сессия мока до загрузки страницы (как cookie портала после входа) и язык, если задан. */
async function signIn(page: Page, role: Role, options: { language?: 'ru' | 'uz' | 'en'; collapsed?: boolean } = {}) {
  await page.route('https://telegram.org/**', (route) => route.fulfill({ contentType: 'text/javascript', body: '' }));
  await page.addInitScript(
    ([session, language, collapsed]) => {
      window.sessionStorage.setItem('cabinet.mock.session', session);
      if (language) window.localStorage.setItem('cabinet.language', language);
      window.localStorage.setItem('rt-cab-sidebar-collapsed-v1', String(collapsed));
    },
    // язык явно: иначе берётся язык контакта из GET /me (у наблюдателя мока — uz)
    [JSON.stringify({ role, auth_method: 'magic_link', dataset: 'demo' }), options.language ?? 'ru', options.collapsed ?? false] as const,
  );
}

/** Mini App: SDK Telegram — заглушка с подписанным `initData` и темой; скрипт telegram.org не грузится. */
async function asMiniApp(page: Page, scheme: 'light' | 'dark', withThemeParams: boolean) {
  const themeParams = !withThemeParams
    ? {}
    : scheme === 'dark'
      ? { bg_color: '#17212b', secondary_bg_color: '#232e3c', section_bg_color: '#17212b', text_color: '#f5f5f5', hint_color: '#708499', button_color: '#5288c1', button_text_color: '#ffffff', accent_text_color: '#6ab2f2', section_separator_color: '#111921', destructive_text_color: '#ec3942' }
      : { bg_color: '#ffffff', secondary_bg_color: '#efeff3', section_bg_color: '#ffffff', text_color: '#000000', hint_color: '#707579', button_color: '#2481cc', button_text_color: '#ffffff', accent_text_color: '#2481cc', section_separator_color: '#e7e7e7', destructive_text_color: '#e53935' };
  const sdk = `window.Telegram = { WebApp: {
    initData: 'query_id=AAE&user=%7B%22id%22%3A42%7D&auth_date=1760400000&hash=signed',
    initDataUnsafe: { user: { id: 42, language_code: 'ru' } },
    colorScheme: '${scheme}', themeParams: ${JSON.stringify(themeParams)},
    BackButton: { isVisible: false, show() {}, hide() {}, onClick() {}, offClick() {} },
    ready() {}, expand() {}, openTelegramLink() {}, onEvent() {}, offEvent() {},
  } };`;
  await page.route('https://telegram.org/**', (route) => route.fulfill({ contentType: 'text/javascript', body: sdk }));
}

const heading = (page: Page, name: string | RegExp) => expect(page.getByRole('heading', { level: 1, name })).toBeVisible();

/** Экраны оболочки: адрес и заголовок h1 (ru), по которому видно, что экран дорисован. */
const SCREENS: Array<{ id: string; path: string; h1: string | RegExp; actorOnly?: boolean }> = [
  { id: 'requests', path: '/requests', h1: 'Запросы' },
  { id: 'request-new', path: '/requests/new', h1: 'Новый запрос', actorOnly: true },
  { id: 'request-detail', path: '/requests/501', h1: 'Запрос Z-2026-0042' },
  { id: 'quotes', path: '/quotes', h1: 'Коммерческие предложения' },
  { id: 'quote-detail', path: '/quotes/301', h1: 'КП KP-2026-0042' },
  { id: 'contracts', path: '/contracts', h1: 'Договоры' },
  { id: 'invoices', path: '/invoices', h1: 'Счета' },
  { id: 'acts', path: '/acts', h1: 'Акты' },
  { id: 'deliveries', path: '/deliveries', h1: 'Поставки' },
  { id: 'documents', path: '/documents', h1: 'Документы' },
  { id: 'catalog', path: '/catalog', h1: 'Каталог' },
  { id: 'catalog-item', path: '/catalog/101', h1: /.+/ },
  { id: 'company', path: '/company', h1: 'Компания' },
  { id: 'team', path: '/team', h1: 'Команда' },
  { id: 'deal', path: '/deals/48', h1: 'Проект D-48' },
  { id: 'profile', path: '/profile', h1: 'Профиль' },
];

/** Ключевые экраны — со снимками в E2E_SCREENS_DIR; остальные — только axe и прокрутка. */
const WITH_SCREENSHOT = new Set(['requests', 'quote-detail', 'deal']);
/** Таблицы проверяются и на 1280 (холст уже из-за сайдбара): без горизонтальной прокрутки. */
const WITH_1280 = new Set(['requests', 'deal', 'invoices', 'quotes', 'contracts', 'acts', 'documents']);
const WIDTHS_1280 = [
  { width: 1440, height: 900 },
  { width: 1280, height: 800 },
  { width: 390, height: 844 },
] as const;

for (const role of ['actor', 'viewer'] as const) {
  test(`все экраны кабинета: ${role}`, async ({ page }) => {
    await signIn(page, role);
    for (const screen of SCREENS) {
      if (screen.actorOnly && role === 'viewer') continue;
      await page.goto(screen.path);
      await heading(page, screen.h1);
      await snap(page, `${role}-${screen.id}`, {
        screenshot: role === 'actor' ? WITH_SCREENSHOT.has(screen.id) || screen.id === 'invoices' : screen.id === 'requests',
        widths: role === 'actor' && WITH_1280.has(screen.id) ? WIDTHS_1280 : undefined,
      });
      if (role === 'actor' && WITH_1280.has(screen.id)) {
        // таблица не прокручивается вбок на 1280: колонки помещаются в холст рядом с развёрнутым сайдбаром
        await page.setViewportSize({ width: 1280, height: 800 });
        await page.waitForTimeout(300);
        const overflow = await page
          .locator('[data-slot="table-container"]')
          .evaluateAll((nodes) => nodes.map((node) => node.scrollWidth - node.clientWidth));
        expect.soft(Math.max(0, ...overflow), `таблица ${screen.id} прокручивается вбок на 1280`).toBeLessThanOrEqual(0);
        await page.setViewportSize({ width: 1440, height: 900 });
      }
    }
  });
}

test('сайдбар свёрнут: пункты с именем, марка RailTech', async ({ page }) => {
  await signIn(page, 'actor', { collapsed: true });
  await page.goto('/deals/48');
  await heading(page, 'Проект D-48');
  const side = page.getByRole('navigation', { name: 'Разделы кабинета' });
  await expect(side.getByRole('link', { name: 'Запросы' })).toBeVisible();
  await expect(page.getByRole('img', { name: /RailTech Cabinet/ })).toBeVisible();
  await snap(page, 'actor-sidebar-collapsed-deal');
});

test('хлебные крошки: номер документа, «Проект» без ссылки', async ({ page }) => {
  await signIn(page, 'actor');
  const crumbs = page.getByRole('navigation', { name: 'Путь к странице' });
  await page.goto('/quotes/301');
  await heading(page, 'КП KP-2026-0042');
  await expect(crumbs).toContainText('KP-2026-0042');
  await page.goto('/deals/48');
  await heading(page, 'Проект D-48');
  await expect(crumbs).toContainText('D-48');
  await expect(crumbs.getByRole('link', { name: 'Проект' })).toHaveCount(0);
  await page.goto('/requests/501');
  await heading(page, 'Запрос Z-2026-0042');
  await expect(crumbs).toContainText('Z-2026-0042');
});

/** Данные из ERP (не тексты интерфейса): название компании и раздел строк КП мока. */
const CLIENT_DATA = [/Тошкент Логистик/, /^Товары$/];

for (const language of ['uz', 'en'] as const) {
  test(`язык ${language}: оболочка и экраны без русских строк интерфейса`, async ({ page }) => {
    await signIn(page, 'actor', { language });
    for (const screen of [
      { id: 'requests', path: '/requests' },
      { id: 'deal', path: '/deals/48' },
      { id: 'quote-detail', path: '/quotes/301' },
    ]) {
      await page.goto(screen.path);
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      // Интерфейс (навигация, шапка, заголовки, кнопки, подписи) — без кириллицы; данные клиента (названия, позиции) — как в ERP
      const chrome = await page
        .locator('nav, header, h1, h2, button, [role="status"], th, label')
        .evaluateAll((nodes) => nodes.map((node) => (node as HTMLElement).innerText).join('\n'));
      const cyrillic = (chrome.match(/[А-Яа-яЁё][^\n]*/g) ?? []).filter((line) => !CLIENT_DATA.some((data) => data.test(line)));
      expect(cyrillic, `кириллица в интерфейсе (${language}, ${screen.path})`).toEqual([]);
      await snap(page, `${language}-${screen.id}`);
    }
  });
}

/**
 * Mini App: оболочка следует themeParams Telegram, если пары проходят AA (CAB-FIX-3, `telegram/theme.ts`): стандартные
 * светлая и тёмная темы Telegram и тёмная тема кабинета без themeParams — axe блокирует все три.
 */
for (const [scheme, params] of [
  ['light', 'telegram'],
  ['dark', 'telegram'],
  ['dark', 'own'],
] as const) {
  test(`Mini App, тема ${scheme} (${params === 'own' ? 'токены кабинета' : 'themeParams Telegram'})`, async ({ page }) => {
    await asMiniApp(page, scheme, params === 'telegram');
    const prefix = `miniapp-${scheme}${params === 'own' ? '-own' : ''}`;
    await page.goto('/deals/48');
    await heading(page, 'Проект D-48');
    expect(await page.evaluate(() => document.documentElement.classList.contains('dark'))).toBe(scheme === 'dark');
    await snap(page, `${prefix}-deal`);
    await page.goto('/requests');
    await heading(page, 'Запросы');
    await snap(page, `${prefix}-requests`);
  });
}

// --- CAB-FIX-3: скачки, бар «Компании», сайдбар без анимации ------------------------------------------------------

for (const size of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
] as const) {
  test(`загрузка «Запросов» без скачка: CLS ≤ 0,01 в 10 прогонах подряд, ${size.width}`, async ({ page }) => {
    await signIn(page, 'actor');
    await page.setViewportSize(size);
    const runs: number[] = [];
    for (let run = 0; run < 10; run += 1) {
      await page.goto('/requests');
      await heading(page, 'Запросы');
      await expect(page.getByRole('region', { name: 'Требует вашего решения' })).toBeVisible();
      await expect(page.getByText('Z-2026-0042').first()).toBeVisible();
      await page.waitForTimeout(400);
      runs.push((await shiftsSince(page)).cls);
    }
    writeCls({ action: 'Загрузка «Запросов»', width: size.width, runs });
    expect(Math.max(...runs), `CLS загрузки по прогонам: ${runs.join(', ')}`).toBeLessThanOrEqual(0.01);
  });

  test(`«Компания»: бар появляется без сдвига формы, одна кнопка «Сохранить», поле над баром, ${size.width}`, async ({ page }) => {
    await signIn(page, 'actor');
    await page.setViewportSize(size);
    await page.goto('/company');
    await heading(page, 'Компания');
    await page.getByRole('button', { name: 'Изменить' }).click();
    const name = page.getByLabel('Название');
    const bank = page.getByLabel('Банковские реквизиты');
    await expect(name).toBeVisible();
    await page.waitForTimeout(600);
    const before = await bank.boundingBox();
    const since = await pageTime(page);

    await page.getByLabel('ИНН').focus();
    await page.keyboard.type('7');
    const bar = page.getByRole('region', { name: 'Несохранённые изменения' });
    await expect(bar).toBeVisible();
    await page.waitForTimeout(400);
    // все сдвиги, включая сразу после ввода: форма не должна прыгать вообще
    const typing = await shiftsSince(page, since, true);
    const after = await bank.boundingBox();
    expect(after?.y, 'форма сдвинулась при появлении бара').toBe(before?.y);
    expect(typing.cls, 'CLS ввода в «Компанию»').toBeLessThanOrEqual(0.01);
    await expect(page.getByRole('button', { name: 'Сохранить' })).toHaveCount(1);

    // поле в фокусе не уходит под бар: последнее поле формы
    await bank.focus();
    await page.keyboard.type(' ');
    await page.waitForTimeout(300);
    const field = await bank.boundingBox();
    const barBox = await bar.boundingBox();
    expect((field?.y ?? 0) + (field?.height ?? 0), 'поле под баром').toBeLessThanOrEqual(barBox?.y ?? 0);
    await snap(page, "actor-company-bar", { widths: [size] });
    writeCls({ action: 'Ввод в «Компанию»', width: size.width, runs: [typing.cls] });

    // «Сбросить» — с подтверждением; после сброса бар невидим, форма на месте
    await bar.getByRole('button', { name: 'Сбросить' }).click();
    await page.getByRole('dialog', { name: 'Сбросить изменения?' }).getByRole('button', { name: 'Сбросить' }).click();
    await expect(bar).toBeHidden();
    expect((await bank.boundingBox())?.y).toBe(before?.y);
  });
}

test('«Компания»: уход по ссылке меню с правками спрашивает', async ({ page }) => {
  await signIn(page, 'actor');
  await page.goto('/company');
  await page.getByRole('button', { name: 'Изменить' }).click();
  await page.getByLabel('ИНН').fill('3051234567');
  await page.getByRole('navigation', { name: 'Разделы кабинета' }).getByRole('link', { name: 'Запросы' }).click();
  const dialog = page.getByRole('dialog', { name: 'Выйти без сохранения?' });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Остаться' }).click();
  await expect(page).toHaveURL(/\/company$/);
  await expect(page.getByLabel('ИНН')).toHaveValue('3051234567');
});

test('⌘\\ / Ctrl+\\: сайдбар без анимации — один шаг, не в поле ввода', async ({ page }) => {
  await signIn(page, 'actor');
  await page.goto('/requests');
  await heading(page, 'Запросы');
  await expect(page.getByText('Z-2026-0042').first()).toBeVisible();
  const aside = page.locator('aside').filter({ has: page.getByRole('navigation', { name: 'Разделы кабинета' }) });
  expect(await aside.evaluate((node) => getComputedStyle(node).transitionDuration)).toBe('0s');
  const width = () => aside.evaluate((node) => node.getBoundingClientRect().width);
  expect(await width()).toBe(256);
  await page.waitForTimeout(600);

  const since = await pageTime(page);
  await page.keyboard.press('Control+Backslash');
  await expect.poll(width).toBe(64);
  await page.waitForTimeout(600);
  const step = await shiftsSince(page, since, true);
  writeCls({ action: '⌘\\ сайдбар (действие пользователя)', width: 1440, runs: [step.cls], frames: step.frames });
  expect(step.frames, 'сдвиг — один кадр, без покадровой анимации').toBeLessThanOrEqual(1);

  // в поле ввода сочетание — тексту, сайдбар не меняется (переход внутри приложения: перезагрузка сбросила бы меню)
  await page.getByRole('navigation', { name: 'Разделы кабинета' }).getByRole('link', { name: 'Каталог' }).click();
  await heading(page, 'Каталог');
  await page.getByRole('searchbox').focus();
  await page.keyboard.press('Control+Backslash');
  await page.waitForTimeout(200);
  expect(await width()).toBe(64);
  await page.keyboard.press('Meta+Backslash');
  await page.waitForTimeout(200);
  expect(await width()).toBe(64);
  await page.locator('main').click({ position: { x: 5, y: 5 } });
  await page.keyboard.press('Control+Backslash');
  await expect.poll(width).toBe(256);
});

test('счета: полоса разделов — навигация ссылками, на 390 подписи целиком; у «Документов» полосы нет', async ({ page }) => {
  await signIn(page, 'actor');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/invoices');
  await heading(page, 'Счета');
  const strip = page.getByRole('navigation', { name: 'Финансовые разделы' });
  await expect(strip.getByRole('link', { name: 'Счета' })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('tablist')).toHaveCount(0);
  for (const name of ['Договоры', 'Счета', 'Акты']) {
    const box = await strip.getByRole('link', { name }).boundingBox();
    expect((box?.x ?? -1) >= 0 && (box?.x ?? 0) + (box?.width ?? 0) <= 390, `«${name}» обрезана`).toBe(true);
  }
  await page.goto('/documents');
  await heading(page, 'Документы');
  await expect(page.getByRole('navigation', { name: 'Финансовые разделы' })).toHaveCount(0);
  await expect(page.getByRole('group', { name: 'Вид документа' })).toBeVisible();
  await page.goto('/deliveries');
  await heading(page, 'Поставки');
  await expect(page.getByRole('navigation', { name: 'Финансовые разделы' })).toHaveCount(0);
});

test('uz: «Loyiha» вместо «Bitim» — проект клиента', async ({ page }) => {
  await signIn(page, 'actor', { language: 'uz' });
  await page.goto('/deals/48');
  await expect(page.getByRole('heading', { level: 1, name: 'Loyiha D-48' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Loyiha bosqichlari' })).toBeVisible();
  await snap(page, 'uz-project');
});

test('вход: демо-блок под своим заголовком, «Войти» — одна кнопка', async ({ page }) => {
  await page.route('https://telegram.org/**', (route) => route.fulfill({ contentType: 'text/javascript', body: '' }));
  await page.goto('/login');
  await heading(page, 'Вход в кабинет');
  await expect(page.getByRole('button', { name: 'Войти', exact: true })).toHaveCount(1);
  await expect(page.getByRole('heading', { level: 2, name: /демо-вход/i })).toBeVisible();
  await snap(page, 'login');
});
