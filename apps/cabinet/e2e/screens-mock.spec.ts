/**
 * CAB-FIX-2 · все экраны кабинета на dev-сборке с моком портального API (MSW), без стенда: `npm run test:e2e:screens`.
 *
 * Роли actor (право действовать) и viewer (только просмотр) × 1440 и 390 px: на каждом экране axe (serious/critical = 0)
 * и отсутствие горизонтальной прокрутки (`snap`, как в гейте M2); сводка — `axe-summary.json` в E2E_SCREENS_DIR.
 * Снимки — только ключевых экранов (запросы, сделка, КП, сайдбар развёрнут и свёрнут), uz и en, тема Mini App
 * (светлая и тёмная themeParams Telegram — SDK подменён заглушкой, вход через `POST /auth/telegram` мока).
 */
import { expect, test, type Page } from '@playwright/test';
import { snap } from './helpers/shots';

type Role = 'actor' | 'viewer';

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
  { id: 'deal', path: '/deals/48', h1: 'Сделка № D-48' },
  { id: 'profile', path: '/profile', h1: 'Профиль' },
];

/** Ключевые экраны — со снимками в docs/screens/cab-fix-2; остальные — только axe и прокрутка. */
const WITH_SCREENSHOT = new Set(['requests', 'quote-detail', 'deal']);

for (const role of ['actor', 'viewer'] as const) {
  test(`все экраны кабинета: ${role}`, async ({ page }) => {
    await signIn(page, role);
    for (const screen of SCREENS) {
      if (screen.actorOnly && role === 'viewer') continue;
      await page.goto(screen.path);
      await heading(page, screen.h1);
      await snap(page, `${role}-${screen.id}`, { screenshot: role === 'actor' ? WITH_SCREENSHOT.has(screen.id) : screen.id === 'requests' });
    }
  });
}

test('сайдбар свёрнут: пункты с именем, марка RailTech', async ({ page }) => {
  await signIn(page, 'actor', { collapsed: true });
  await page.goto('/deals/48');
  await heading(page, 'Сделка № D-48');
  const side = page.getByRole('navigation', { name: 'Разделы кабинета' });
  await expect(side.getByRole('link', { name: 'Запросы' })).toBeVisible();
  await expect(page.getByRole('img', { name: /RailTech Cabinet/ })).toBeVisible();
  await snap(page, 'actor-sidebar-collapsed-deal');
});

test('хлебные крошки: номер документа, «Сделка» без ссылки', async ({ page }) => {
  await signIn(page, 'actor');
  const crumbs = page.getByRole('navigation', { name: 'Путь к странице' });
  await page.goto('/quotes/301');
  await heading(page, 'КП KP-2026-0042');
  await expect(crumbs).toContainText('KP-2026-0042');
  await page.goto('/deals/48');
  await heading(page, 'Сделка № D-48');
  await expect(crumbs).toContainText('D-48');
  await expect(crumbs.getByRole('link', { name: 'Сделка' })).toHaveCount(0);
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
 * Mini App: оболочка следует themeParams Telegram, как в main. С палитрами самого Telegram (button_color и hint_color
 * как текст: 3,6–4,2:1) axe не блокирует — нарушения пишутся в сводку; тёмная тема кабинета без themeParams (наши
 * токены .dark из packages/ui-tokens) — блокирует.
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
    await heading(page, 'Сделка № D-48');
    expect(await page.evaluate(() => document.documentElement.classList.contains('dark'))).toBe(scheme === 'dark');
    await snap(page, `${prefix}-deal`, { blocking: params === 'own' });
    await page.goto('/requests');
    await heading(page, 'Запросы');
    await snap(page, `${prefix}-requests`, { blocking: params === 'own' });
  });
}

test('вход: демо-блок под своим заголовком, «Войти» — одна кнопка', async ({ page }) => {
  await page.route('https://telegram.org/**', (route) => route.fulfill({ contentType: 'text/javascript', body: '' }));
  await page.goto('/login');
  await heading(page, 'Вход в кабинет');
  await expect(page.getByRole('button', { name: 'Войти', exact: true })).toHaveCount(1);
  await expect(page.getByRole('heading', { level: 2, name: /демо-вход/i })).toBeVisible();
  await snap(page, 'login');
});
