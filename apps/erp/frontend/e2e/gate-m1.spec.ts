/**
 * Гейт M1 (FIX-50; повтор после раунда 2 — FIX-50b): прогон пути бэк-офиса BUSINESS §4–§11 на СТЕНДЕ ансамбля —
 * настоящие CRM и ERP, без моков.
 *
 *   заявка (CRM → «Передать в бэк-офис») → КП (строки, курс, маржа) → согласование (цепочка ролей) → отправка
 *   клиенту → публичная ссылка и акцепт → договор → счёт и оплата → поставка → акт
 *
 * Роли: «Руководитель» (роль HEAD), «Расчёт», «Финансы», «Наблюдатель» и Администратор CRM (= суперпользователь
 * ERP). Сотрудников заводит CRM («Пользователи» → «Доступ к ERP», FIX-11), системную роль ERP выдаёт админ в
 * «Настройки → Команда» (настоящий пользователь с настоящей ролью, `/me` не подменяется). Клиент — публичная
 * страница КП (браузер) и портал (шаги клиента по API; UI Cabinet — FIX-51).
 *
 * НЕ запускается в CI и по умолчанию: без переменных окружения весь файл пропускается. Запуск (из apps/erp/frontend):
 *
 *   E2E_BASE_URL=http://erp.localhost:8088 E2E_CRM_URL=http://crm.localhost:8088 \
 *   E2E_CRM_ADMIN_EMAIL=… E2E_CRM_ADMIN_PASSWORD=… \
 *   E2E_MAIL_LOG_CMD='cd <корень> && docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env \
 *                     logs --no-log-prefix --since 15m {svc} 2>&1' \
 *   npx playwright test e2e/gate-m1.spec.ts --workers=1
 *
 * Скриншоты (1440 и 390 px) и `axe-results.json` пишутся в `docs/screens/fix-50b/` (или `E2E_SHOTS_DIR`).
 *
 * Дефекты раунда 1 (docs/runbooks/m1_qa_02_report.md), исправленные в раунде 2, проверяются здесь строго: тест красный,
 * если дефект вернулся. Дефекты, которые не исправлены, помечены `test.fail()` (красный «как ожидалось»; когда
 * дефект исправят, тест «неожиданно пройдёт» — аннотацию снимают).
 */
import { expect, request as pwRequest, test, type Browser, type BrowserContext, type Page } from '@playwright/test';
import Decimal from 'decimal.js';
import { readFileSync } from 'node:fs';
import path from 'node:path';

import {
  ENV,
  PERSONAS,
  apiHeaders,
  allBlockingAxe,
  closeDialogs,
  crmLogin,
  ensureCrmUser,
  erpGet,
  gateEnabled,
  lastToast,
  loadState,
  openErpSession,
  portalGet,
  portalLogin,
  portalPost,
  probe,
  saveState,
  serviceLog,
  shoot,
  shootDialog,
  ssoClickThrough,
  ssoStats,
  waitMail,
  writeAxeReport,
  type Persona,
  type PortalClient,
  type Session,
} from './gate-m1.helpers';

test.skip(!gateEnabled, 'гейт M1 идёт против стенда: нужны E2E_BASE_URL, E2E_CRM_URL, E2E_CRM_ADMIN_*, E2E_MAIL_LOG_CMD');

test.describe.configure({ mode: 'serial' });

const S = loadState();
const sessions = new Map<Persona, Session>();
const crmPasswords = new Map<Persona, string>([['admin', ENV.adminPassword]]);
let crmAdmin: { ctx: BrowserContext; page: Page } | null = null;
let client: PortalClient | null = null;
const dupRef = { sameStatus: 0, sameIdSame: false, otherStatus: 0, otherDetail: '', paidAfter: '' };
/** Экраны, которые у открытой сессии не обновились по возврату на вкладку (D-09). */
const staleViews: string[] = [];
/** Экраны, где данные пришли только после возврата на вкладку (событие `focus`) — так и должно быть (D-09, FIX-58). */
const refreshedOnFocus: string[] = [];
/** Находки проверки 390 px конструктора КП (D-13): пусто = страница не шире экрана и кнопки в кадре. */
const narrowFindings: string[] = [];
/** Наблюдения по текстам (D-12), которые не входят в строгие проверки. */
const textObservations: string[] = [];
/** Показал ли экран сделки «от имени» в журнале (D-02, шаг 3.2). */
const onBehalfOnScreen = { value: false };
/** Имя менеджера на публичной странице КП — то, что видит клиент (шаг 5.2). */
const publicManager = { name: '' };

const STAFF: Persona[] = ['calc', 'fin', 'viewer', 'head'];


// ── общие шаги ─────────────────────────────────────────────────────────────────

async function getCrmAdmin(browser: Browser): Promise<Page> {
  if (!crmAdmin) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'ru-RU' });
    const page = await ctx.newPage();
    await crmLogin(page, ENV.adminEmail, ENV.adminPassword);
    crmAdmin = { ctx, page };
  }
  return crmAdmin.page;
}

async function getSession(browser: Browser, persona: Persona): Promise<Session> {
  const known = sessions.get(persona);
  if (known) return known;
  if (!crmPasswords.has(persona)) {
    const admin = await getCrmAdmin(browser);
    crmPasswords.set(persona, await ensureCrmUser(admin, PERSONAS[persona]));
  }
  const { session, crmPassword } = await openErpSession(browser, persona, crmPasswords.get(persona)!);
  crmPasswords.set(persona, crmPassword);
  sessions.set(persona, session);
  return session;
}

/** Клиент в портале: один вход на прогон (лимит magic-link — 5 в час на адрес). */
async function getClient(): Promise<PortalClient> {
  if (!client) client = await portalLogin(S.contactEmail, S.contactName);
  return client;
}

/**
 * Ждёт элемент. Если открытая сессия его не показывает, имитирует «пользователь вернулся на вкладку» (событие `focus`
 * окна — тот же сигнал, что слушает кэш запросов, FIX-58 D-09) и ждёт ещё. Если элемент так и не появился —
 * экран устарел (D-09 жив): фиксируем, перезагружаем страницу и идём дальше.
 */
async function visibleOrReload(page: Page, target: ReturnType<Page['locator']>, label: string): Promise<void> {
  const quick = await target
    .waitFor({ state: 'visible', timeout: 4_000 })
    .then(() => true)
    .catch(() => false);
  if (quick) return;
  await returnToTab(page);
  const afterFocus = await target
    .waitFor({ state: 'visible', timeout: 8_000 })
    .then(() => true)
    .catch(() => false);
  if (afterFocus) {
    refreshedOnFocus.push(label);
    return;
  }
  staleViews.push(label);
  await page.reload();
  await expect(target).toBeVisible({ timeout: 20_000 });
}

/** «Вернулся на вкладку»: окно получает `focus`, документ — `visibilitychange` (React Query перечитывает живые списки). */
async function returnToTab(page: Page): Promise<void> {
  await page.evaluate(() => {
    window.dispatchEvent(new Event('focus'));
    document.dispatchEvent(new Event('visibilitychange'));
  });
}

async function goErp(page: Page, hash: string): Promise<void> {
  // Переход может быть прерван встречной навигацией SPA (ERR_ABORTED) — повторяем, это не дефект экрана.
  for (let attempt = 0; ; attempt++) {
    try {
      await page.goto(`${ENV.erp}/#${hash}`);
      break;
    } catch (e) {
      if (attempt >= 3 || !/ERR_ABORTED|interrupted by another navigation/.test(String(e))) throw e;
      await page.waitForTimeout(1_500);
    }
  }
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(1500);
}

function dealHash(): string {
  return `request-detail/${S.dealId}`;
}

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any -- ответы API стенда, схема в OpenAPI

async function quoteJson(ctx: BrowserContext): Promise<Json> {
  return erpGet<Json>(ctx, `crm/quotes/${S.quoteId}/`);
}

async function listResults(ctx: BrowserContext, apiPath: string): Promise<Json[]> {
  const data = await erpGet<Json | Json[]>(ctx, apiPath);
  return Array.isArray(data) ? data : ((data as Json).results as Json[]);
}

async function dialogButton(page: Page, name: string | RegExp) {
  return page.getByRole('dialog').getByRole('button', { name, exact: typeof name === 'string' });
}

function money(value: unknown): Decimal {
  return new Decimal(String(value));
}

async function addQuoteLine(page: Page, name: string, qty: string, costUsd: string): Promise<void> {
  const nameInput = page.getByPlaceholder('Наименование позиции...');
  if (!(await nameInput.isVisible())) await page.getByRole('button', { name: 'Добавить', exact: true }).first().click();
  await nameInput.fill(name);
  await page.getByLabel('Кол-во', { exact: true }).fill(qty);
  const cost = page.getByLabel('Себестоимость, за ед.', { exact: true });
  await cost.fill(costUsd);
  const saved = page.waitForResponse((r) => r.url().includes('/crm/quote-items/') && r.request().method() === 'POST');
  await cost.press('Enter');
  expect((await saved).status()).toBe(201);
}

/**
 * Проба «состав и цены КП меняются?» (D-04, FIX-55): все пути записи, которые меняют сумму КП, на текущем этапе.
 * Вне черновика каждый обязан ответить 409 (`QUOTE_NOT_DRAFT`, после отправки `QUOTE_FROZEN`), в черновике — пройти.
 * Пробы безвредны, если защита работает; если нет — тест 5.4 красный, а данные прогона уже не годятся.
 */
const lockProbes: Record<string, Record<string, { status: number; detail: string }>> = {};

async function probeQuoteLock(ctx: BrowserContext, label: string): Promise<void> {
  const q = await quoteJson(ctx);
  const item = (q.items as Json[])[0];
  const types = await erpGet<Json[] | { results: Json[] }>(ctx, 'crm/charge-types/');
  const chargeType = String((Array.isArray(types) ? types : types.results)[0].code);
  const id = S.quoteId;
  const r: Record<string, { status: number; detail: string }> = {};
  r['PATCH позиции'] = await probe(ctx, 'patch', `crm/quote-items/${item.id}/`, { note: `FIX-50b проба (${label})` });
  r['POST позиции'] = await probe(ctx, 'post', 'crm/quote-items/', { quote: id, title: 'FIX-50b проба', quantity: 1, unit_cost: '1' });
  r['DELETE позиции'] = await probe(ctx, 'delete', `crm/quote-items/${item.id}/`);
  r['bulk-update'] = await probe(ctx, 'post', 'crm/quote-items/bulk-update/', { quote: id, items: [{ id: item.id, note: 'FIX-50b' }] });
  r['bulk-create'] = await probe(ctx, 'post', 'crm/quote-items/bulk-create/', {
    quote: id,
    items: [{ imported_raw_name: 'FIX-50b проба', quantity: 1, unit_cost: '1' }],
  });
  r['bulk-delete'] = await probe(ctx, 'post', 'crm/quote-items/bulk-delete/', { quote: id, items: [item.id] });
  r['POST расхода'] = await probe(ctx, 'post', 'crm/quote-charges/', {
    quote: id,
    charge_type: chargeType,
    description: 'FIX-50b проба',
    amount: '1.00',
  });
  r['PATCH КП (НДС)'] = await probe(ctx, 'patch', `crm/quotes/${id}/`, { vat_rate: '0' });
  lockProbes[label] = r;
  console.log(`D-04 [${label}]:`, Object.entries(r).map(([k, v]) => `${k}=${v.status}${v.detail ? ' ' + v.detail : ''}`).join('; '));
}

/** Число из строки «Итого к оплате …» публичной страницы КП — то, что видит клиент. */
function publicTotal(body: string): string {
  return (/Итого к оплате[^\d]*([\d\s\u00a0\u202f.,]+\d)/.exec(body)?.[1] ?? '').replace(/[\s\u00a0\u202f]/g, '');
}
let publicTotalBefore = '';

test.beforeAll(() => {
  if (!S.companyName) {
    S.companyName = `FIX-50b Тест ООО ${S.run}`;
    S.contactName = `FIX-50b Клиент ${S.run}`;
    S.contactEmail = `fix50b-lead-${S.run}@example.com`;
    saveState(S);
  }
});

test.afterAll(async () => {
  writeAxeReport();
  for (const s of sessions.values()) await s.ctx.close();
  if (crmAdmin) await crmAdmin.ctx.close();
});

// ═══ 0. Сотрудники через CRM ═══════════════════════════════════════════════════

test('0.1 CRM «Пользователи»: сотрудники ролей заведены, доступ к ERP выдан (FIX-11)', async ({ browser }) => {
  test.setTimeout(300_000);
  const admin = await getCrmAdmin(browser);
  for (const p of STAFF) crmPasswords.set(p, await ensureCrmUser(admin, PERSONAS[p]));
  await admin.goto(`${ENV.crm}/users`);
  await expect(admin.locator('tr', { hasText: ENV.adminEmail })).toBeVisible();
  for (const p of STAFF) {
    await expect(admin.locator('tr', { hasText: PERSONAS[p].email }).getByRole('switch')).toHaveAttribute(
      'aria-checked',
      'true',
    );
  }
  await shoot(admin, 'crm-users', 'admin');
});

test('0.3 ERP «Настройки → Команда»: админ выдаёт системные роли; права по `/me` = каталог ролей (CONVENTIONS.md §6)', async ({
  browser,
}) => {
  test.setTimeout(300_000);
  const admin = await getSession(browser, 'admin');
  await goErp(admin.page, 'settings');
  await admin.page.goto(`${ENV.erp}/?section=team#settings`);
  await expect(admin.page.getByText('Команда компании')).toBeVisible();
  for (const p of STAFF) {
    const info = PERSONAS[p];
    const row = admin.page.locator('tr', { hasText: info.email }).first();
    await expect(row).toBeVisible();
    await row.getByRole('button', { name: /Выбрать роли/ }).click();
    // D-15 (FIX-55): роли «CRM Sync: …» ведёт CRM — в списке выбора их нет ни чужих, ни своей.
    const names = await admin.page.getByRole('menuitemcheckbox').allInnerTexts();
    expect(names.filter((n) => /CRM Sync/.test(n)), `${p}: в выборе ролей «CRM Sync» быть не должно`).toEqual([]);
    expect(names, 'выбор ролей содержит системную роль').toContain(info.erpRole);
    const item = admin.page.getByRole('menuitemcheckbox', { name: info.erpRole!, exact: true });
    if ((await item.getAttribute('aria-checked')) !== 'true') await item.click();
    await expect(item).toHaveAttribute('aria-checked', 'true');
    await closeDialogs(admin.page);
    await admin.page.waitForTimeout(600);
  }
  // Экран «Команда» не раскрывает служебные роли и чужие e-mail в ролях.
  await expect(admin.page.getByText(/CRM Sync/)).toHaveCount(0);
  await shoot(admin.page, 'settings-team', 'admin');

  for (const p of STAFF) {
    const s = await getSession(browser, p);
    const me = await erpGet<Json>(s.ctx, 'accounts/users/me/');
    const perms = (me.capabilities.permissions as string[]).slice().sort();
    if (PERSONAS[p].permissions === 'ALL') {
      expect(perms.length, `${p}: все 22 права`).toBe(22);
    } else {
      expect(perms, `${p}: права роли «${PERSONAS[p].erpRole}»`).toEqual([...(PERSONAS[p].permissions as string[])].sort());
    }
    expect(me.capabilities.crm_access, `${p}: кнопка «В CRM» — по сопоставлению CRM`).toBe(true);
    // D-12 (FIX-55): имя из CRM делится на имя и фамилию, а не остаётся инициалом «F.».
    expect(String(me.first_name ?? '').length, `${p}: имя заполнено`).toBeGreaterThan(1);
    expect(String(me.last_name ?? '').length, `${p}: фамилия заполнена`).toBeGreaterThan(1);
  }
});

// ═══ 1. Заявка: CRM → ERP ══════════════════════════════════════════════════════

test('1.1 Заявка: веб-форма → лид CRM → «Передать в бэк-офис» → заявка в ERP', async ({ browser }) => {
  test.setTimeout(3_300_000);
  const admin = await getCrmAdmin(browser);

  // Входная дверь стенда без бота — публичная форма «Запрос» (с согласием на ПДн, Q-12).
  const api = await pwRequest.newContext({ baseURL: ENV.crm });
  // Форма ограничена 5 запросами в час с одного IP (`rate_limit_per_hour`): при 429 ждём освобождения окна.
  let sent = await api.get('/api/v1/leads/web/token'); // заглушка для типа; перезаписывается ниже
  for (let attempt = 0; attempt < 45; attempt++) {
    const tk = (await (await api.get('/api/v1/leads/web/token')).json()) as { token: string; min_fill_seconds: number };
    await new Promise((r) => setTimeout(r, (tk.min_fill_seconds + 1) * 1000));
    sent = await api.post('/api/v1/leads/web', {
      data: {
        form_token: tk.token,
        name: S.contactName,
        company: S.companyName,
        email: S.contactEmail,
        phone: `+99890${String(parseInt(S.run, 16)).padStart(7, '0').slice(-7)}`,
        language: 'ru',
        consent: true,
        text: `FIX-50b (${S.run}): рельсовые скрепления КБ-65 — 200 комплектов; шефмонтаж — 1 услуга. КП до пятницы.`,
      },
    });
    if (sent.status() !== 429) break;
    await new Promise((r) => setTimeout(r, 60_000));
  }
  expect(sent.status()).toBe(202);
  S.leadId = ((await sent.json()) as { lead_id: number }).lead_id;
  saveState(S);

  await admin.goto(`${ENV.crm}/leads/${S.leadId}`);
  await admin.getByRole('button', { name: 'Забрать' }).click();
  await expect(admin.getByRole('button', { name: 'Передать в бэк-офис' }).first()).toBeVisible();
  await shoot(admin, 'crm-lead-before-handoff', 'admin');
  await admin.getByRole('button', { name: 'Передать в бэк-офис' }).first().click();
  const dlg = admin.getByRole('dialog');
  await dlg.getByPlaceholder('или новый клиент').fill(S.companyName);
  await dlg.getByRole('button', { name: 'Передать в бэк-офис' }).click();
  const badge = admin.getByText(/В бэк-офисе: Заявка #\d+/);
  await expect(badge).toBeVisible({ timeout: 60_000 });
  S.dealId = Number(/#(\d+)/.exec(await badge.innerText())![1]);
  saveState(S);
  await shoot(admin, 'crm-lead-handed-off', 'admin');

  const calc = await getSession(browser, 'calc');
  await goErp(calc.page, dealHash());
  await expect(calc.page.getByText(`Заявка: ${S.companyName}`).first()).toBeVisible({ timeout: 30_000 });
});

test('1.2 D-11 (FIX-57): лид из звонка — «Согласие получено» в карточке → «Передать в бэк-офис» → заявка в ERP', async ({
  browser,
}) => {
  test.setTimeout(240_000);
  const admin = await getCrmAdmin(browser);
  await admin.goto(`${ENV.crm}/inbox`);
  await admin.getByRole('button', { name: 'Новый лид' }).click();
  const dlg = admin.getByRole('dialog');
  const manualCompany = `FIX-50b Ручной ООО ${S.run}`;
  await dlg.locator('#name').fill(`FIX-50b Звонок ${S.run}`);
  await dlg.locator('#company').fill(manualCompany);
  await dlg.locator('#phone').fill(`+99891${String(parseInt(S.run, 16)).padStart(7, '0').slice(-7)}`);
  await dlg.locator('#need').fill(`FIX-50b (${S.run}): звонок — болты М20, 500 штук, нужна цена.`);
  await dlg.getByRole('button', { name: 'Создать', exact: true }).click();
  await admin.waitForURL(/\/leads\/\d+/, { timeout: 30_000 }).catch(async () => {
    await admin.getByRole('link', { name: /FIX-50b Звонок/ }).first().click();
    await admin.waitForURL(/\/leads\/\d+/);
  });
  S.manualLeadId = Number(/\/leads\/(\d+)/.exec(admin.url())![1]);
  saveState(S);

  // Без согласия передать нельзя; «Согласие получено» — штатный путь для звонка (раньше его не было, D-11).
  await expect(admin.getByRole('button', { name: 'Согласие получено' }).first()).toBeVisible();
  await shoot(admin, 'crm-lead-manual-before-consent', 'admin');
  await admin.getByRole('button', { name: 'Согласие получено' }).first().click();
  const consent = admin.getByRole('dialog');
  await consent.getByRole('button', { name: 'Согласие получено' }).click();
  await expect(admin.getByRole('dialog')).toHaveCount(0, { timeout: 15_000 });
  await expect(admin.getByRole('button', { name: 'Передать в бэк-офис' }).first()).toBeVisible();
  await shoot(admin, 'crm-lead-manual-consent-recorded', 'admin');

  await admin.getByRole('button', { name: 'Передать в бэк-офис' }).first().click();
  const handoff = admin.getByRole('dialog');
  await handoff.getByPlaceholder('или новый клиент').fill(manualCompany);
  await handoff.getByRole('button', { name: 'Передать в бэк-офис' }).click();
  const badge = admin.getByText(/В бэк-офисе: Заявка #\d+/);
  await expect(badge).toBeVisible({ timeout: 60_000 });
  S.manualDealId = Number(/#(\d+)/.exec(await badge.innerText())![1]);
  saveState(S);
  await shoot(admin, 'crm-lead-manual-handed-off', 'admin');
});

// ═══ 2. Расчёт: заявка → КП ════════════════════════════════════════════════════

test('2.1 «Расчёт»: очередь, карточка заявки, «Взять в работу», стадии', async ({ browser }) => {
  test.setTimeout(180_000);
  const calc = await getSession(browser, 'calc');
  await goErp(calc.page, 'crm-deals');
  await expect(calc.page.getByText(`Заявка: ${S.companyName}`).first()).toBeVisible();
  await shoot(calc.page, 'deals-list', 'calc');

  await goErp(calc.page, dealHash());
  await expect(calc.page.getByText('Комментарий клиента')).toBeVisible();
  await shoot(calc.page, 'request-detail-new', 'calc');

  await calc.page.getByRole('button', { name: 'Взять в работу', exact: true }).click();
  await expect(calc.page.getByRole('button', { name: 'Вернуть в очередь' })).toBeVisible();
  await calc.page.getByRole('button', { name: 'К подбору' }).click();
  await expect(calc.page.getByRole('button', { name: 'Начать расчёт' })).toBeVisible();
  await calc.page.getByRole('button', { name: 'Начать расчёт' }).click();
  await expect(calc.page.getByText('Расчёт', { exact: true }).first()).toBeVisible();

  // ИИ-черновик: на стенде нет ключей провайдеров — ограничение стенда, не дефект; фиксируем, как это выглядит.
  await calc.page.getByRole('button', { name: 'Взять в работу и подготовить КП' }).click();
  const toast = await lastToast(calc.page);
  test.info().annotations.push({ type: 'ИИ (ограничение стенда)', description: toast || 'тост не показан' });
  await shoot(calc.page, 'request-detail-in-work', 'calc');
});

test('2.2 «Расчёт»: КП — строки (товар и услуга), курс, маржа', async ({ browser }) => {
  test.setTimeout(180_000);
  const calc = await getSession(browser, 'calc');
  await goErp(calc.page, `deal-quote/${S.dealId}`);
  await calc.page.getByRole('button', { name: 'Создать КП' }).first().click();
  const created = calc.page.waitForResponse((r) => /\/crm\/quotes\/$/.test(r.url()) && r.request().method() === 'POST');
  await (await dialogButton(calc.page, 'Создать КП')).click();
  const res = await created;
  expect(res.status()).toBe(201);
  S.quoteId = ((await res.json()) as { id: number }).id;
  saveState(S);

  await addQuoteLine(calc.page, 'Скрепление рельсовое КБ-65 FIX-50b', '200', '120');
  await addQuoteLine(calc.page, 'Шефмонтаж FIX-50b (услуга)', '1', '1500');
  await expect(calc.page.getByText('Позиций: 2')).toBeVisible();

  const q = await quoteJson(calc.ctx);
  expect(q.items).toHaveLength(2);
  expect(money(q.total_incl_vat).gt(0), 'итог КП посчитан').toBe(true);
  // Наценка 20 % на себестоимость → маржа 16,67 % (порог 15 %).
  expect(Math.abs(Number(q.economics?.gross_margin_percent ?? q.margin_percent) - 16.67)).toBeLessThan(0.1);
  // D-13 (FIX-58): конструктор КП на 390 px — страница не шире экрана, «Сохранить» и кнопка панели согласования в кадре.
  await calc.page.setViewportSize({ width: 390, height: 844 });
  await calc.page.waitForTimeout(800);
  const narrow = await calc.page.evaluate(() => {
    const vw = window.innerWidth;
    const out: string[] = [];
    if (document.documentElement.scrollWidth > vw + 1) out.push(`страница шире экрана: ${document.documentElement.scrollWidth} > ${vw}`);
    for (const b of Array.from(document.querySelectorAll('button'))) {
      const label = (b.getAttribute('aria-label') || b.textContent || '').trim();
      if (!/^(Сохранить|Открыть панель согласования|Добавить)$/.test(label)) continue;
      const r = b.getBoundingClientRect();
      if (r.width && (r.right > vw + 1 || r.left < -1)) out.push(`«${label}» вне экрана (${Math.round(r.left)}…${Math.round(r.right)})`);
    }
    return out;
  });
  narrowFindings.push(...narrow);
  await calc.page.setViewportSize({ width: 1440, height: 900 });
  await calc.page.waitForTimeout(500);
  await shoot(calc.page, 'quote-builder-draft', 'calc');

  // «Расчёт» договорной курс не меняет — кнопки нет, сервер отказывает.
  await expect(calc.page.getByRole('button', { name: 'Изменить курс' })).toHaveCount(0);
  const denied = await probe(calc.ctx, 'post', `crm/quotes/${S.quoteId}/fx-override/`, { rate: '12500', reason: 'FIX-50b' });
  expect(denied).toMatchObject({ status: 403, detail: 'ROLE_NOT_PERMITTED' });
});

test('2.3 «Финансы»: договорной курс USD с причиной (fx-override), КП пересчитывается', async ({ browser }) => {
  test.setTimeout(180_000);
  const fin = await getSession(browser, 'fin');
  await goErp(fin.page, `deal-quote/${S.dealId}`);
  const openFx = async () => {
    const btn = fin.page.getByRole('button', { name: 'Изменить курс' });
    if (!(await btn.isVisible())) await fin.page.getByRole('button', { name: 'Развернуть панель' }).click();
    await btn.click();
  };
  await shootDialog(fin.page, 'quote-fx-dialog', 'fin', openFx);
  await openFx();
  const fx = fin.page.getByRole('dialog').getByRole('textbox');
  await fx.first().fill('12500');
  await fx.last().fill('FIX-50b: курс по договору с клиентом');
  const saved = fin.page.waitForResponse((r) => r.url().includes('/fx-override/') && r.request().method() === 'POST');
  await (await dialogButton(fin.page, 'Сохранить курс')).click();
  expect((await saved).status()).toBe(200);

  const q = await quoteJson(fin.ctx);
  // (200 × 120 + 1 × 1500) USD × 12 500 × 1,2 = 382 500 000 без НДС; НДС 12 % = 45 900 000; итого 428 400 000.
  expect(money(q.subtotal_excl_vat).toFixed(2)).toBe('382500000.00');
  expect(money(q.vat_amount).toFixed(2)).toBe('45900000.00');
  expect(money(q.total_incl_vat).toFixed(2)).toBe('428400000.00');
  await goErp(fin.page, `deal-quote/${S.dealId}`);
  await shoot(fin.page, 'quote-builder-fx', 'fin');
});

// ═══ 3. Согласование ═══════════════════════════════════════════════════════════

test('3.1 Согласование: «Расчёт» отправляет, цепочка ролей, финальное утверждение — только «Руководитель»', async ({
  browser,
}) => {
  test.setTimeout(300_000);
  const calc = await getSession(browser, 'calc');
  await goErp(calc.page, `deal-quote/${S.dealId}`);
  const openPanel = async () => {
    await calc.page.getByRole('button', { name: 'Открыть панель согласования' }).click({ force: true });
  };
  await shootDialog(calc.page, 'quote-approval-preview', 'calc', openPanel);
  await openPanel();
  await calc.page.getByRole('button', { name: 'На согласование' }).click();
  await expect(calc.page.getByRole('dialog').getByText('КП находится на согласовании')).toBeVisible();
  await closeDialogs(calc.page);
  await shootDialog(calc.page, 'quote-approval-chain', 'calc', openPanel);
  await probeQuoteLock(calc.ctx, 'на согласовании');
  // D-03/D-04 в интерфейсе: на согласовании конструктор КП — только чтение (правок, которые сервер всё равно отклонит, нет).
  await goErp(calc.page, `deal-quote/${S.dealId}`);
  await expect(calc.page.getByText('Только чтение').first()).toBeVisible();
  for (const name of ['Добавить', 'Сохранить']) {
    await expect(calc.page.getByRole('button', { name, exact: true }), `«${name}» вне черновика`).toHaveCount(0);
  }
  await expect(calc.page.getByRole('button', { name: /Удалить (позицию|строку)/ })).toHaveCount(0);
  await shoot(calc.page, 'quote-builder-pending', 'calc');

  const q = await quoteJson(calc.ctx);
  expect(q.status_code).toBe('PENDING_APPROVAL');
  const headStep = (q.approval_steps as Json[]).find((s) => s.participation === 'HEAD');
  expect(headStep, 'в цепочке есть шаг руководителя').toBeTruthy();
  const decide = { step_id: headStep!.id, decision: 'APPROVE' };

  // Финальный шаг — только держатель quote.approve_final.
  expect(await probe(calc.ctx, 'post', `crm/quotes/${S.quoteId}/approval-act/`, decide)).toMatchObject({
    status: 403,
    detail: 'ROLE_NOT_PERMITTED',
  });
  const fin = await getSession(browser, 'fin');
  expect(await probe(fin.ctx, 'post', `crm/quotes/${S.quoteId}/approval-act/`, decide)).toMatchObject({ status: 403 });
  const viewer = await getSession(browser, 'viewer');
  expect(await probe(viewer.ctx, 'post', `crm/quotes/${S.quoteId}/approval-act/`, decide)).toMatchObject({ status: 403 });
});

test('3.2 D-02 (FIX-55): автор КП не согласует своё КП; суперпользователь за другого — «от имени» в журнале', async ({
  browser,
}) => {
  test.setTimeout(240_000);
  const calc = await getSession(browser, 'calc');
  const q = await quoteJson(calc.ctx);
  const steps = q.approval_steps as Json[];
  // Автор в цепочке не значится как проверяющий: его место не создаётся.
  expect(
    steps.filter((st) => String(st.approver_name).includes(PERSONAS.calc.fullName)),
    'в цепочке нет места автора',
  ).toEqual([]);
  const reviewer = steps.find((st) => st.participation === 'APPROVER' && st.status === 'PENDING');
  expect(reviewer, 'в цепочке есть шаг проверяющего').toBeTruthy();
  // Автор пробует закрыть чужое место проверяющего (держатель quote.review) — отказ.
  expect(await probe(calc.ctx, 'post', `crm/quotes/${S.quoteId}/approval-act/`, { step_id: reviewer!.id, decision: 'APPROVE' })).toMatchObject({
    status: 403,
    detail: 'SELF_APPROVAL_NOT_ALLOWED',
  });
  // Панель согласования у автора: кнопок «Согласовать» на шагах проверяющих нет в списке его собственных действий.
  await goErp(calc.page, `deal-quote/${S.dealId}`);
  await calc.page.getByRole('button', { name: 'Открыть панель согласования' }).click({ force: true });
  await expect(calc.page.getByRole('dialog').getByText(PERSONAS.calc.fullName, { exact: true })).toHaveCount(0);
  await closeDialogs(calc.page);

  // Суперпользователь (админ ERP) закрывает шаг другого согласующего: запись в журнале помечена «от имени».
  const admin = await getSession(browser, 'admin');
  const onBehalf = await probe(admin.ctx, 'post', `crm/quotes/${S.quoteId}/approval-act/`, { step_id: reviewer!.id, decision: 'APPROVE' });
  expect(onBehalf.status, 'суперпользователь закрывает шаг за коллегу').toBe(200);
  // Журнал (API): запись о шаге несёт «от имени» и параметр `on_behalf_of` (кто и за кого).
  const timeline = await erpGet<Json[] | { results: Json[] }>(admin.ctx, `crm/timeline/?deal_id=${S.dealId}&limit=100`);
  const entries = Array.isArray(timeline) ? timeline : timeline.results;
  const onBehalfEntry = entries.find((e) => JSON.stringify(e).includes('on_behalf_of'));
  console.log('D-02 журнал (API):', onBehalfEntry ? JSON.stringify(onBehalfEntry).replace(/\s+/g, ' ').slice(0, 400) : 'записи с on_behalf_of нет');
  expect(onBehalfEntry, 'в журнале есть запись «от имени» (on_behalf_of)').toBeTruthy();
  // Журнал (экран сделки): та же запись читается человеком.
  await goErp(admin.page, dealHash());
  await admin.page.waitForTimeout(2_500);
  const shownOnScreen = /от имени/.test(await admin.page.locator('body').innerText());
  console.log('D-02 журнал (экран сделки) показывает «от имени»:', shownOnScreen);
  onBehalfOnScreen.value = shownOnScreen;
  await shoot(admin.page, 'request-detail-on-behalf', 'admin');
});

test('3.3 «Руководитель» проходит все шаги цепочки → «Готово к отправке»', async ({ browser }) => {
  test.setTimeout(300_000);
  const head = await getSession(browser, 'head');
  await goErp(head.page, `deal-quote/${S.dealId}`);
  await head.page.getByRole('button', { name: 'Открыть панель согласования' }).click({ force: true });
  const dlg = head.page.getByRole('dialog');
  let approved = 0;
  for (let i = 0; i < 30; i++) {
    const next = dlg.getByRole('button', { name: 'Согласовать' }).first();
    if (!(await next.count())) break;
    const act = head.page.waitForResponse((r) => r.url().includes('/approval-act/'));
    await next.click();
    if ((await act).status() === 200) approved += 1;
    await head.page.waitForTimeout(1_200); // дать панели перерисоваться: иначе повторный клик по прежней кнопке даёт 400
  }
  expect(approved, 'шагов, пройденных руководителем').toBeGreaterThanOrEqual(1);
  await expect(dlg.getByText('КП согласовано внутри компании и готово к отправке клиенту.')).toBeVisible();
  await closeDialogs(head.page);
  await shootDialog(head.page, 'quote-approval-done', 'head', async () => {
    await head.page.getByRole('button', { name: 'Открыть панель согласования' }).click({ force: true });
  });
  const q = await quoteJson(head.ctx);
  expect(q.status_code).toBe('READY_TO_SEND');
  const calc = await getSession(browser, 'calc');
  await probeQuoteLock(calc.ctx, 'утверждено, до отправки');
});

// ═══ 4. Наблюдатель — только чтение ════════════════════════════════════════════

test('4.1 «Наблюдатель»: экраны открываются, финансов и себестоимости нет', async ({ browser }) => {
  test.setTimeout(240_000);
  const v = await getSession(browser, 'viewer');
  await goErp(v.page, 'dashboard');
  await shoot(v.page, 'dashboard', 'viewer');
  await goErp(v.page, 'crm-deals');
  await shoot(v.page, 'deals-list', 'viewer');
  await goErp(v.page, dealHash());
  await expect(v.page.getByText(`Заявка: ${S.companyName}`).first()).toBeVisible();
  // Маржа и факт закупки — только с quote.view_cost_margin.
  await expect(v.page.getByText('Маржа сделки: КП и факт закупки')).toHaveCount(0);
  await shoot(v.page, 'request-detail', 'viewer');
  await goErp(v.page, `deal-quote/${S.dealId}`);
  await expect(v.page.getByText('Себестоимость', { exact: false })).toHaveCount(0);
  await expect(v.page.getByText('Валовая прибыль')).toHaveCount(0);
  await shoot(v.page, 'quote-builder', 'viewer');
});

test('4.2 D-03 (FIX-58): у «Наблюдателя» кнопок действий нет — ни на сделке, ни в конструкторе КП; конструктор «только чтение»', async ({
  browser,
}) => {
  test.setTimeout(120_000);
  const v = await getSession(browser, 'viewer');
  await goErp(v.page, dealHash());
  await expect(v.page.getByText(`Заявка: ${S.companyName}`).first()).toBeVisible();
  const actions = ['Взять в работу', 'К подбору', 'Создать документ', 'Вернуть в очередь', 'На согласование', 'Отправить КП'];
  const shown: string[] = [];
  for (const name of actions) {
    if (await v.page.getByRole('button', { name, exact: true }).count()) shown.push(name);
  }
  await goErp(v.page, `deal-quote/${S.dealId}`);
  // «Экспорт» (просмотр, печать, PDF) — чтение документа, у Наблюдателя остаётся.
  for (const name of ['Добавить', 'Сохранить', 'Создать договор', 'Отправить КП', 'Изменить курс']) {
    if (await v.page.getByRole('button', { name, exact: true }).count()) shown.push(name);
  }
  if (await v.page.getByRole('button', { name: /Удалить (позицию|строку)/ }).count()) shown.push('Удалить позицию');
  expect(shown, 'кнопки действий, видимые Наблюдателю').toEqual([]);
  await expect(v.page.getByText('Только чтение').first()).toBeVisible();
  // Просмотр остаётся: позиции и итоги видны, колонок себестоимости и наценки нет (нет права quote.view_cost_margin).
  await expect(v.page.getByText('Позиций: 2')).toBeVisible();
  await expect(v.page.getByRole('columnheader', { name: /Себестоимость|Наценка/ })).toHaveCount(0);
});

// ═══ 5. Отправка клиенту, публичная ссылка ═════════════════════════════════════

test('5.1 «Расчёт» отправляет КП клиенту; ссылка из «Копировать ссылку» = публичный токен КП', async ({ browser }) => {
  test.setTimeout(180_000);
  const calc = await getSession(browser, 'calc');
  await calc.ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: ENV.erp });
  await goErp(calc.page, `deal-quote/${S.dealId}`);
  const sendVisible = await calc.page
    .getByRole('button', { name: 'Отправить КП' })
    .first()
    .waitFor({ state: 'visible', timeout: 5_000 })
    .then(() => true)
    .catch(() => false);
  if (!sendVisible) {
    // D-09: у автора КП открытая сессия могла показать прежний статус (согласование прошёл другой человек).
    // Возврат на вкладку (focus) обязан перечитать КП (FIX-58); иначе — перезагрузка и дефект жив.
    await returnToTab(calc.page);
    const afterFocus = await calc.page
      .getByRole('button', { name: 'Отправить КП' })
      .first()
      .waitFor({ state: 'visible', timeout: 8_000 })
      .then(() => true)
      .catch(() => false);
    if (afterFocus) {
      refreshedOnFocus.push('КП: «Отправить КП» после согласования другим сотрудником');
    } else {
      staleViews.push('КП: «Отправить КП» после согласования другим сотрудником');
      await calc.page.reload();
    }
  }
  const openSend = async () => {
    await calc.page.getByRole('button', { name: 'Отправить КП' }).first().click();
  };
  await shootDialog(calc.page, 'quote-send-dialog', 'calc', openSend);
  await openSend();
  if (/не требуется — согласовано автоматически/.test(await calc.page.getByRole('dialog').innerText())) {
    textObservations.push('Диалог «Отправить КП»: «Согласование: не требуется — согласовано автоматически» при пройденной вручную цепочке');
  }
  const sent = calc.page.waitForResponse((r) => r.url().includes('/send-to-client/'));
  await (await dialogButton(calc.page, 'Отправить КП')).click();
  expect((await sent).status()).toBe(200);
  await expect(calc.page.getByText('КП отправлено', { exact: true }).first()).toBeVisible();

  const q = await quoteJson(calc.ctx);
  S.quoteNumber = String(q.number);
  saveState(S);
  expect(q.status_code).toBe('SENT');
  expect(q.public_access_token, 'у отправленного КП есть публичный токен').toBeTruthy();

  await calc.page.getByRole('button', { name: 'Копировать ссылку' }).click();
  const copied = await calc.page.evaluate(() => navigator.clipboard.readText());
  expect(copied.endsWith(`/api/v1/public/quotes/${q.public_access_token}/`), 'в буфер попала ссылка этого КП').toBe(true);
  await shoot(calc.page, 'quote-sent', 'calc');
  await probeQuoteLock(calc.ctx, 'отправлено клиенту');
  // D-03/D-04: отправленное КП — конструктор только для чтения, без «Добавить», «Сохранить», «Удалить позицию».
  await goErp(calc.page, `deal-quote/${S.dealId}`);
  await expect(calc.page.getByText('Только чтение').first()).toBeVisible();
  for (const name of ['Добавить', 'Сохранить']) {
    await expect(calc.page.getByRole('button', { name, exact: true }), `«${name}» в отправленном КП`).toHaveCount(0);
  }
  await expect(calc.page.getByRole('button', { name: /Удалить (позицию|строку)/ })).toHaveCount(0);
  await shoot(calc.page, 'quote-builder-sent', 'calc');
});

test('5.2 Клиент по публичной ссылке: страница КП, PDF, без себестоимости и маржи; чужой токен — 404', async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const calc = await getSession(browser, 'calc');
  const q = await quoteJson(calc.ctx);
  const link = `${ENV.erp}/api/v1/public/quotes/${q.public_access_token}/`;
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'ru-RU' });
  const page = await ctx.newPage();
  const resp = await page.goto(link);
  expect(resp!.status()).toBe(200);
  expect(resp!.headers()['content-type']).toContain('text/html');
  const body = await page.locator('body').innerText();
  expect(body).toContain(S.quoteNumber);
  expect(body).toContain('Итого к оплате');
  expect(body).not.toMatch(/себестоим|маржа|наценк|fx|курс цб/i);
  publicManager.name = (/Менеджер\s*\n?\s*([^\n\t]+)/.exec(body)?.[1] ?? '').trim();
  publicTotalBefore = publicTotal(body);
  expect(publicTotalBefore, 'на публичной странице виден итог КП').not.toBe('');
  await expect(page.getByRole('button', { name: /Принять предложение/ })).toBeVisible();
  await shoot(page, 'public-quote', 'client');

  const pdf = await ctx.request.get(link);
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()['content-type']).toContain('application/pdf');
  expect((await pdf.body()).subarray(0, 5).toString()).toBe('%PDF-');

  const stranger = await ctx.request.get(`${ENV.erp}/api/v1/public/quotes/fix50b-no-such-token-0000000000/`, {
    headers: { Accept: 'text/html' },
  });
  expect(stranger.status()).toBe(404);
  await ctx.close();
});

test('5.3 Клиент принимает КП: код из письма, неверный код отклоняется, договор создаётся сам', async ({ browser }) => {
  test.setTimeout(240_000);
  const calc = await getSession(browser, 'calc');
  const q = await quoteJson(calc.ctx);
  const link = `${ENV.erp}/api/v1/public/quotes/${q.public_access_token}/`;
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'ru-RU' });
  const page = await ctx.newPage();
  await page.goto(link);
  await page.getByRole('button', { name: /Принять предложение/ }).click();
  await page.getByRole('button', { name: /Отправить код/ }).click();
  await expect(page.getByText(/Код отправлен/)).toBeVisible();
  await shoot(page, 'public-quote-code', 'client');

  await page.getByLabel('Код из письма').fill('000000');
  await page.getByRole('button', { name: 'Принять предложение' }).last().click();
  await expect(page.getByText('Неверный код')).toBeVisible();
  await expect(page.getByText('Предложение принято')).toBeHidden();

  const code = await waitMail(S.contactEmail, [S.quoteNumber], /Ваш код:\s*(\d{4,12})/);
  await page.getByLabel('Код из письма').fill(code);
  await page.getByRole('button', { name: 'Принять предложение' }).last().click();
  await expect(page.getByText('Предложение принято')).toBeVisible({ timeout: 20_000 });
  await shoot(page, 'public-quote-accepted', 'client');
  await ctx.close();

  const after = await quoteJson(calc.ctx);
  expect(after.status_code).toBe('APPROVED');
  const contracts = await listResults(calc.ctx, 'crm/contracts/');
  const mine = contracts.find((c) => Number(c.deal?.id ?? c.deal) === S.dealId);
  expect(mine, 'договор создан по акцепту').toBeTruthy();
  S.contractId = mine!.id as number;
  saveState(S);
  await probeQuoteLock(calc.ctx, 'принято клиентом');
  await goErp(calc.page, `deal-quote/${S.dealId}`);
  await expect(calc.page.getByText('Только чтение').first()).toBeVisible();
  await shoot(calc.page, 'quote-builder-accepted', 'calc');
});

test('5.4 D-04 (P0, FIX-55): вне черновика состав и цены КП не меняются — 409 на всех путях записи; клиент видит прежнюю сумму', async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const stages = ['на согласовании', 'утверждено, до отправки', 'отправлено клиенту', 'принято клиентом'];
  const bad: string[] = [];
  for (const stage of stages) {
    const r = lockProbes[stage];
    expect(r, `пробы этапа «${stage}» выполнены`).toBeTruthy();
    for (const [path, res] of Object.entries(r)) {
      const want = stage === 'отправлено клиенту' || stage === 'принято клиентом' ? 'QUOTE_FROZEN' : 'QUOTE_NOT_DRAFT';
      if (res.status !== 409 || res.detail !== want) bad.push(`${stage}: ${path} → ${res.status} ${res.detail} (ждали 409 ${want})`);
    }
  }
  expect(bad, 'пути записи, не ответившие 409').toEqual([]);

  // Позиции и итог на месте; публичная страница показывает ту же сумму, что до проб.
  const calc = await getSession(browser, 'calc');
  const q = await quoteJson(calc.ctx);
  expect(q.items).toHaveLength(2);
  expect(money(q.total_incl_vat).toFixed(2)).toBe('428400000.00');
  expect(q.status_code).toBe('APPROVED');
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'ru-RU' });
  const page = await ctx.newPage();
  await page.goto(`${ENV.erp}/api/v1/public/quotes/${q.public_access_token}/`);
  expect(publicTotal(await page.locator('body').innerText()), 'сумма на странице клиента не изменилась').toBe(publicTotalBefore);
  await ctx.close();
});

// ═══ 6. Договор ════════════════════════════════════════════════════════════════

test('6.1 Договор: клиент подписывает в портале, «Руководитель» — в ERP; «Расчёт» и «Финансы» подписать не могут', async ({
  browser,
}) => {
  test.setTimeout(300_000);
  const head = await getSession(browser, 'head');
  const calc = await getSession(browser, 'calc');
  const fin = await getSession(browser, 'fin');

  // Без права contract.sign — 403 (подпись компании «Руководителем» — ниже, после клиента).
  expect(await probe(calc.ctx, 'post', `crm/contracts/${S.contractId}/sign-manager/`)).toMatchObject({
    status: 403,
    detail: 'ROLE_NOT_PERMITTED',
  });
  expect(await probe(fin.ctx, 'post', `crm/contracts/${S.contractId}/sign-manager/`)).toMatchObject({ status: 403 });

  const cl = await getClient();
  const list = await portalGet<Json[]>(cl, 'contracts');
  const mine = list.body.find((c) => c.deal.id === `D-${S.dealId}` || c.deal.id === S.dealId || c.id === S.contractId);
  expect(mine, 'договор виден клиенту').toBeTruthy();
  if (mine!.status === 'sent') {
    const signed = await portalPost<Json>(cl, `contracts/${S.contractId}/sign`);
    expect(signed.status).toBe(200);
    expect(signed.body.status).toBe('signed_by_client');
  } else {
    expect(['signed_by_client', 'signed'], 'повтор прогона: клиент уже подписал').toContain(mine!.status);
  }

  await goErp(head.page, dealHash());
  await expect(head.page.getByText('Договор ждёт вашей подписи')).toBeVisible();
  await shoot(head.page, 'request-detail-contract-sign', 'head');
  const openContract = async () => {
    await goErp(head.page, dealHash()); // «Подписать» ведёт на экран «Договоры» с шторкой — после закрытия возвращаемся к сделке
    await head.page.getByRole('button', { name: 'Подписать', exact: true }).click();
  };
  await shootDialog(head.page, 'contract-drawer', 'head', openContract);
  await openContract();
  // D-12 (FIX-58): в шторке договора после подписи клиента нет «null · дата» и прочих сырых значений.
  const drawerText = await head.page.getByRole('dialog').innerText();
  expect(drawerText, 'шторка договора без «null»/«undefined»').not.toMatch(/\bnull\b|\bundefined\b|NaN/);
  const signManager = head.page.waitForResponse((r) => r.url().includes('/sign-manager/'));
  await (await dialogButton(head.page, 'Подписать (продавец)')).click();
  expect((await signManager).status()).toBe(200);
  await expect(head.page.getByRole('dialog').getByText('Подписан', { exact: true }).first()).toBeVisible();
  await goErp(head.page, 'contracts');
  await shoot(head.page, 'contracts', 'head');
});

test('6.2 Портал: чужие запросы, КП и документы клиенту недоступны (404)', async () => {
  const cl = await getClient();
  const foreign = Array.from({ length: S.dealId + 3 }, (_, i) => i + 1).filter((id) => id !== S.dealId);
  for (const id of foreign.slice(0, 12)) {
    expect((await portalGet(cl, `requests/${id}`)).status, `requests/${id}`).toBe(404);
  }
  for (const id of Array.from({ length: S.quoteId + 2 }, (_, i) => i + 1).filter((i) => i !== S.quoteId).slice(0, 12)) {
    expect((await portalGet(cl, `quotes/${id}`)).status, `quotes/${id}`).toBe(404);
  }
  // Документы: id = pk × 8 + слот вида; соседние pk того же вида принадлежат другим компаниям или не существуют.
  const mine = (await portalGet<Json[]>(cl, 'documents')).body.map((d) => Number(d.id));
  expect(mine.length, 'свои документы клиента (КП, договор)').toBeGreaterThanOrEqual(2);
  const strangers = [...new Set(mine.flatMap((id) => [id - 8, id - 16, id + 8]))].filter((id) => id > 0 && !mine.includes(id));
  for (const id of strangers.slice(0, 20)) {
    const res = await cl.api.get(`/api/portal/v1/documents/${id}/file`);
    expect(res.status(), `documents/${id}/file`).toBe(404);
  }
});

// ═══ 7. Счёт и оплата ══════════════════════════════════════════════════════════

test('7.1 «Финансы»: счёт из договора выставляется клиенту', async ({ browser }) => {
  test.setTimeout(180_000);
  const fin = await getSession(browser, 'fin');
  await goErp(fin.page, dealHash());
  await expect(fin.page.getByText('Счёт готов черновиком')).toBeVisible();
  await shoot(fin.page, 'request-detail-invoice-draft', 'fin');
  const openInvoice = async () => {
    await goErp(fin.page, dealHash()); // «Открыть счёт» ведёт на экран «Счета» с шторкой
    await fin.page.getByRole('button', { name: 'Открыть счёт' }).click();
    const shown = await fin.page
      .getByRole('dialog')
      .waitFor({ state: 'visible', timeout: 6_000 })
      .then(() => true)
      .catch(() => false);
    if (!shown) {
      // D-09: список счетов мог быть запрошен до создания счёта. Возврат на вкладку (focus) обязан его перечитать (FIX-58).
      await returnToTab(fin.page);
      let afterFocus = await fin.page
        .getByRole('dialog')
        .waitFor({ state: 'visible', timeout: 6_000 })
        .then(() => true)
        .catch(() => false);
      if (!afterFocus) {
        const again = fin.page.getByRole('button', { name: 'Открыть счёт' });
        if (await again.count()) await again.click();
        afterFocus = await fin.page
          .getByRole('dialog')
          .waitFor({ state: 'visible', timeout: 6_000 })
          .then(() => true)
          .catch(() => false);
      }
      if (afterFocus) {
        refreshedOnFocus.push('Счета: шторка счёта после создания счёта другим сотрудником');
      } else {
        staleViews.push('Счета: шторка счёта после создания счёта другим сотрудником');
        await goErp(fin.page, dealHash());
        await fin.page.reload();
        await fin.page.getByRole('button', { name: 'Открыть счёт' }).click();
      }
    }
  };
  await openInvoice();
  const drawer = fin.page.getByRole('dialog');
  S.invoiceNumber = (/INV-\d{4}-\d+/.exec(await drawer.innerText()) ?? [''])[0];
  expect(S.invoiceNumber).toMatch(/^INV-\d{4}-\d+$/);
  await closeDialogs(fin.page);
  await shootDialog(fin.page, 'invoice-drawer', 'fin', openInvoice);
  await openInvoice();
  const issued = fin.page.waitForResponse((r) => r.url().includes('/issue/'));
  await (await dialogButton(fin.page, 'Выставить')).click();
  expect((await issued).status()).toBe(200);

  const invoices = await listResults(fin.ctx, 'crm/invoices/');
  const mine = invoices.find((i) => i.number === S.invoiceNumber);
  expect(mine, 'счёт в списке').toBeTruthy();
  S.invoiceId = mine!.id as number;
  saveState(S);
  expect(money(mine!.total_incl_vat).toFixed(2)).toBe('428400000.00');
  await goErp(fin.page, 'invoices');
  await shoot(fin.page, 'invoices', 'fin');
});

test('7.2 Оплата: «Расчёт» платёж не фиксирует; сверх остатка — отказ; частичная и полная оплата', async ({ browser }) => {
  test.setTimeout(240_000);
  const fin = await getSession(browser, 'fin');
  const calc = await getSession(browser, 'calc');
  const today = new Date().toISOString().slice(0, 10);

  expect(
    await probe(calc.ctx, 'post', `crm/invoices/${S.invoiceId}/record-payment/`, { amount: '1000', paid_at: today, reference: 'x' }),
  ).toMatchObject({ status: 403, detail: 'ROLE_NOT_PERMITTED' });
  expect(
    await probe(fin.ctx, 'post', `crm/invoices/${S.invoiceId}/record-payment/`, {
      amount: '999999999999.00',
      paid_at: today,
      reference: `FIX-50b сверх остатка ${S.run}`,
    }),
  ).toMatchObject({ status: 400, detail: 'PAYMENT_EXCEEDS_BALANCE_DUE' });

  const pay = async (amount: string, reference: string) => {
    await fin.page.getByRole('button', { name: 'Записать платёж' }).first().click();
    const d = fin.page.getByRole('dialog');
    await d.getByRole('combobox').first().click();
    await fin.page.getByRole('option', { name: new RegExp(S.invoiceNumber) }).click();
    await d.getByPlaceholder('0.00').fill(amount);
    await d.getByPlaceholder(/платёжного поручения/).fill(reference);
    const done = fin.page.waitForResponse((r) => r.url().includes('/record-payment/'));
    await d.getByRole('button', { name: 'Сохранить' }).click();
    expect((await done).status()).toBe(201);
  };

  await goErp(fin.page, 'payments');
  const advanceRef = `FIX-50b аванс ${S.run}`;
  await pay('100000000', advanceRef);
  let inv = await erpGet<Json>(fin.ctx, `crm/invoices/${S.invoiceId}/`);
  expect(money(inv.amount_paid).toFixed(2)).toBe('100000000.00');
  expect(inv.status).toBe('PARTIAL');
  await shoot(fin.page, 'payments', 'fin');

  // D-05 (FIX-55): тот же банковский референс. Другая сумма — 409 PAYMENT_REFERENCE_CONFLICT (деньги не теряются молча);
  // та же сумма и дата — повторная отправка: 200 и прежний платёж, оплачено не растёт.
  const apiHeadersCache = await apiHeaders(fin.ctx);
  const record = (data: Record<string, string>) =>
    fin.ctx.request.post(`${ENV.erp}/api/v1/crm/invoices/${S.invoiceId}/record-payment/`, {
      headers: apiHeadersCache,
      data,
    });
  const conflict = await record({ amount: '1000.00', paid_at: today, reference: advanceRef });
  dupRef.otherStatus = conflict.status();
  dupRef.otherDetail = String(((await conflict.json().catch(() => ({}))) as Json).detail ?? '');
  inv = await erpGet<Json>(fin.ctx, `crm/invoices/${S.invoiceId}/`);
  dupRef.paidAfter = money(inv.amount_paid).toFixed(2);

  const replayRef = `FIX-50b повтор ${S.run}`;
  const first = await record({ amount: '1000.00', paid_at: today, reference: replayRef });
  expect(first.status(), 'новый референс — платёж записан').toBe(201);
  const firstBody = (await first.json()) as Json;
  const paidMid = money((await erpGet<Json>(fin.ctx, `crm/invoices/${S.invoiceId}/`)).amount_paid).toFixed(2);
  const again = await record({ amount: '1000.00', paid_at: today, reference: replayRef });
  dupRef.sameStatus = again.status();
  dupRef.sameIdSame = ((await again.json()) as Json).id === firstBody.id;
  const paidEnd = money((await erpGet<Json>(fin.ctx, `crm/invoices/${S.invoiceId}/`)).amount_paid).toFixed(2);
  console.log(
    'D-05: другая сумма —', dupRef.otherStatus, dupRef.otherDetail, '| повтор той же — ', dupRef.sameStatus,
    'тот же платёж:', dupRef.sameIdSame, '| оплачено до/после повтора:', paidMid, paidEnd,
  );
  expect(paidEnd, 'повтор не удваивает платёж').toBe(paidMid);

  // Остаток считаем по факту счёта: в нём уже есть платёж 1000 из проверки повтора.
  inv = await erpGet<Json>(fin.ctx, `crm/invoices/${S.invoiceId}/`);
  const rest = money(inv.total_incl_vat).minus(money(inv.amount_paid)).toFixed(2);
  await pay(rest, `FIX-50b доплата ${S.run}`);
  inv = await erpGet<Json>(fin.ctx, `crm/invoices/${S.invoiceId}/`);
  expect(money(inv.amount_paid).toFixed(2)).toBe('428400000.00');
  expect(inv.status).toBe('PAID');
  // Закрытый счёт новых платежей не принимает.
  expect(
    await probe(fin.ctx, 'post', `crm/invoices/${S.invoiceId}/record-payment/`, {
      amount: '1.00',
      paid_at: today,
      reference: `FIX-50b после закрытия ${S.run}`,
    }),
  ).toMatchObject({ status: 400, detail: 'INVOICE_ALREADY_PAID' });
});

test('7.3 D-05 (FIX-55): тот же референс — другая сумма 409 PAYMENT_REFERENCE_CONFLICT; та же сумма и дата — 200 и прежний платёж', async () => {
  expect(dupRef.otherStatus, 'шаг 7.2 выполнен').toBeGreaterThan(0);
  expect(dupRef.otherStatus, 'другая сумма при том же референсе').toBe(409);
  expect(dupRef.otherDetail).toBe('PAYMENT_REFERENCE_CONFLICT');
  expect(dupRef.paidAfter, 'конфликт не изменил оплачено').toBe('100000000.00');
  expect(dupRef.sameStatus, 'повторная отправка той же суммы и даты').toBe(200);
  expect(dupRef.sameIdSame, 'в ответе прежний платёж').toBe(true);
});

// ═══ 8. Поставка и акт ═════════════════════════════════════════════════════════

test('8.1 «Руководитель»: статусы поставки; клиент принимает строки в портале', async ({ browser }) => {
  test.setTimeout(300_000);
  const head = await getSession(browser, 'head');
  await goErp(head.page, 'fulfillments');
  const row = () => head.page.locator('tr', { hasText: `#${S.dealId}` }).first();
  await visibleOrReload(head.page, row(), 'Исполнение: строка поставки новой сделки');
  const update = async (status: string, track?: string) => {
    await row().getByRole('button', { name: 'Обновить статус' }).click();
    const d = head.page.getByRole('dialog');
    await d.getByRole('combobox').click();
    await head.page.getByRole('option', { name: status, exact: true }).click();
    if (track) {
      await d.getByLabel('Трек-номер').fill(track);
      await d.getByLabel('Перевозчик').fill('FIX-50b Логистика');
    }
    const done = head.page.waitForResponse((r) => r.url().includes('/fulfillments/update-status/'));
    await d.getByRole('button', { name: 'Обновить статус' }).click();
    expect((await done).status()).toBe(200);
  };
  await update('Отгружено');
  await update('В пути', `FIX50-${S.run}`);
  await shoot(head.page, 'fulfillments', 'head');
  await update('Доставлено');
  await expect(row().getByText('Доставлено')).toBeVisible();

  const cl = await getClient();
  const lines = await portalGet<Json[]>(cl, 'deliveries');
  const mine = lines.body.filter((l) => l.status === 'delivered' && /FIX-50b/.test(l.title));
  expect(mine.length, 'строки поставки видны клиенту как доставленные').toBeGreaterThanOrEqual(2);
  for (const line of mine) {
    const acc = await portalPost<Json>(cl, `deliveries/${line.id}/accept`);
    expect(acc.status).toBe(200);
    expect(acc.body.status).toBe('accepted');
  }
});

test('8.2 Акт: «Руководитель» выпускает из счёта, клиент принимает в портале', async ({ browser }) => {
  test.setTimeout(240_000);
  const head = await getSession(browser, 'head');
  await goErp(head.page, 'invoices');
  await visibleOrReload(head.page, head.page.locator('tr', { hasText: S.invoiceNumber }).first(), 'Счета: счёт, выставленный другим сотрудником');
  await head.page.locator('tr', { hasText: S.invoiceNumber }).first().getByText(S.invoiceNumber).click();
  const gen = head.page.waitForResponse((r) => r.url().includes('/generate-act/'));
  await (await dialogButton(head.page, 'Сформировать акт')).click();
  expect((await gen).status()).toBe(201);
  await goErp(head.page, 'acts');
  await shoot(head.page, 'acts', 'head');

  const cl = await getClient();
  const acts = await portalGet<Json[]>(cl, 'acts');
  const mine = acts.body.find((a) => a.deal.id === `D-${S.dealId}` || a.deal.id === S.dealId);
  expect(mine, 'акт виден клиенту').toBeTruthy();
  const accepted = await portalPost<Json>(cl, `acts/${mine!.id}/accept`);
  expect(accepted.status).toBe(200);

  await goErp(head.page, dealHash());
  await expect(head.page.getByText('Цепочка сделки')).toBeVisible();
  await shoot(head.page, 'request-detail-chain-final', 'head');
  const calc = await getSession(browser, 'calc');
  await goErp(calc.page, dealHash());
  await shoot(calc.page, 'request-detail-chain-final', 'calc');
  const fin = await getSession(browser, 'fin');
  await goErp(fin.page, dealHash());
  await shoot(fin.page, 'request-detail-chain-final', 'fin');
  const viewer = await getSession(browser, 'viewer');
  await goErp(viewer.page, dealHash());
  await shoot(viewer.page, 'request-detail-chain-final', 'viewer');
});

// ═══ 9. Матрица прав: отказы и дашборды ════════════════════════════════════════

test('9.1 Матрица прав: мутации без права → 403 ROLE_NOT_PERMITTED (Наблюдатель, «Расчёт», «Финансы»)', async ({
  browser,
}) => {
  test.setTimeout(240_000);
  const sess = { viewer: await getSession(browser, 'viewer'), calc: await getSession(browser, 'calc'), fin: await getSession(browser, 'fin') };
  const today = new Date().toISOString().slice(0, 10);
  const cases: Array<[Exclude<Persona, 'admin' | 'head'>, 'post', string, unknown]> = [
    ['viewer', 'post', `crm/deals/${S.dealId}/claim/`, {}],
    ['viewer', 'post', `crm/quotes/${S.quoteId}/submit-for-review/`, {}],
    ['viewer', 'post', 'crm/quote-items/', { quote: S.quoteId, title: 'FIX-50b проба', quantity: 1, unit_cost: '1' }],
    ['viewer', 'post', `crm/quotes/${S.quoteId}/send-to-client/`, {}],
    ['viewer', 'post', `crm/quotes/${S.quoteId}/fx-override/`, { rate: '12500', reason: 'FIX-50b' }],
    ['viewer', 'post', `crm/contracts/${S.contractId}/sign-manager/`, {}],
    ['viewer', 'post', `crm/invoices/${S.invoiceId}/issue/`, {}],
    ['viewer', 'post', `crm/invoices/${S.invoiceId}/record-payment/`, { amount: '1', paid_at: today, reference: 'x' }],
    ['viewer', 'post', `crm/invoices/${S.invoiceId}/generate-act/`, {}],
    ['viewer', 'post', 'crm/fulfillments/update-status/', { deal_id: S.dealId, status_code: 'SHIPPED' }],
    ['calc', 'post', `crm/invoices/${S.invoiceId}/issue/`, {}],
    ['calc', 'post', `crm/invoices/${S.invoiceId}/generate-act/`, {}],
    ['calc', 'post', 'crm/fulfillments/update-status/', { deal_id: S.dealId, status_code: 'SHIPPED' }],
    ['fin', 'post', `crm/deals/${S.dealId}/claim/`, {}],
    ['fin', 'post', `crm/quotes/${S.quoteId}/submit-for-review/`, {}],
    ['fin', 'post', 'crm/quote-items/', { quote: S.quoteId, title: 'FIX-50b проба', quantity: 1, unit_cost: '1' }],
    ['fin', 'post', `crm/quotes/${S.quoteId}/send-to-client/`, {}],
    ['fin', 'post', `crm/contracts/${S.contractId}/sign-manager/`, {}],
    ['fin', 'post', `crm/invoices/${S.invoiceId}/generate-act/`, {}],
  ];
  const wrong: string[] = [];
  for (const [who, method, path, data] of cases) {
    const r = await probe(sess[who].ctx, method, path, data);
    if (r.status !== 403) wrong.push(`${who} ${method.toUpperCase()} ${path} → ${r.status} ${r.detail}`);
  }
  expect(wrong, 'мутации без права, не получившие 403').toEqual([]);
});

test('9.2 Экраны ролей: дашборд, договоры, счета, настройки (скриншоты 1440/390 и axe)', async ({ browser }) => {
  test.setTimeout(420_000);
  for (const p of ['head', 'calc', 'fin'] as Persona[]) {
    const s = await getSession(browser, p);
    await goErp(s.page, 'dashboard');
    await shoot(s.page, 'dashboard', p);
  }
  const v = await getSession(browser, 'viewer');
  for (const [hash, name] of [['contracts', 'contracts'], ['invoices', 'invoices'], ['payments', 'payments'], ['settings', 'settings']] as const) {
    await goErp(v.page, hash);
    await shoot(v.page, name, 'viewer');
  }
  const calc = await getSession(browser, 'calc');
  await goErp(calc.page, 'crm-quotes');
  await shoot(calc.page, 'quotes-list', 'calc');
  await goErp(calc.page, 'clients');
  await shoot(calc.page, 'clients', 'calc');
});

// ═══ 10. Исправления раунда 2 и итоги ═════════════════════════════════════════

const RAW_CODES = /\b(IN_TRANSIT|DELIVERED|ISSUED|SHIPPED|READY_TO_SEND|PENDING_[A-Z_]+|CLOSED_WON|CONTRACT_SIGNED|PARTIAL|PAID|SENT|DRAFT|ACCEPTED|CANCELLED)\b/;

test('10.1 D-12 (FIX-58): тексты — валюта позиции, журнал без [MANUAL_MODE], без сырых кодов', async ({ browser }) => {
  test.setTimeout(180_000);
  const head = await getSession(browser, 'head');
  await goErp(head.page, dealHash());
  await expect(head.page.getByText('Цепочка сделки')).toBeVisible();
  await head.page.waitForTimeout(1_500);
  const deal = await head.page.locator('body').innerText();
  // Базовая цена позиции в валюте себестоимости (USD), а не «120,00 UZS».
  expect(deal, 'цена позиции в USD не подписана как UZS').not.toMatch(/120[,.]00\s*UZS/);
  expect(deal, 'журнал сделки без служебной метки').not.toMatch(/\[MANUAL_MODE\]/);
  expect(deal, 'карточка сделки без сырых кодов статусов').not.toMatch(RAW_CODES);
  await shoot(head.page, 'request-detail-journal', 'head');

  const calc = await getSession(browser, 'calc');
  await goErp(calc.page, 'crm-quotes');
  await calc.page.waitForTimeout(1_500);
  const quotes = await calc.page.locator('body').innerText();
  if (!new RegExp(`${S.quoteNumber}`).test(quotes) || /#\d+-v\d+/.test(quotes)) {
    textObservations.push('Список КП: номера в виде «#N-vM», а не «КП-…»');
  }
  await goErp(calc.page, `deal-quote/${S.dealId}`);
  if (/Quote Builder/.test(await calc.page.locator('body').innerText())) {
    textObservations.push('Конструктор КП: англоязычный подзаголовок «Quote Builder — …» на русском экране');
  }
  await goErp(calc.page, 'clients');
  if (/\bclients\b/.test(await calc.page.locator('header, nav').allInnerTexts().then((t) => t.join(' ')))) {
    textObservations.push('Клиенты: хлебная крошка «clients» латиницей');
  }
  console.log('D-12, наблюдения по текстам:', textObservations.join(' | ') || 'нет');
});

test('10.1b D-12 (исправлено частично): дашборд — «Недавние документы» без сырых кодов статусов (DELIVERED/ISSUED печатаются кодом)', async ({
  browser,
}) => {
  test.fail(true, 'D-12: в «Недавних документах» дашборда статусы накладной и квитанции печатаются кодом (DELIVERED, ISSUED)');
  const head = await getSession(browser, 'head');
  await goErp(head.page, 'dashboard');
  await head.page.waitForTimeout(2_000);
  const body = await head.page.locator('body').innerText();
  console.log('D-12, сырые коды на дашборде:', [...new Set(body.match(new RegExp(RAW_CODES, 'g')) ?? [])].join(', ') || 'нет');
  expect(body, 'дашборд без сырых кодов статусов').not.toMatch(RAW_CODES);
});

test('10.2 D-13 (FIX-58): конструктор КП на 390 px — страница не шире экрана, кнопки в кадре', async () => {
  expect(narrowFindings, 'находки проверки 390 px (шаг 2.2, черновик КП)').toEqual([]);
});

test('10.3 D-14 (FIX-54/55): токен публичной ссылки КП не попадает в журнал erp-backend', async ({ browser }) => {
  test.setTimeout(120_000);
  const calc = await getSession(browser, 'calc');
  const q = await quoteJson(calc.ctx);
  const token = String(q.public_access_token);
  expect(token.length, 'токен КП получен').toBeGreaterThan(16);
  const log = serviceLog('erp-backend');
  // Контроль: запросы к публичным КП в журнале есть (иначе «токена нет» ничего не доказывает).
  expect(log, 'в журнале есть запросы к публичным ссылкам КП').toMatch(/\/public\/quotes\//);
  expect(log.includes(token), 'полный токен публичной ссылки в журнале erp-backend').toBe(false);
});

test('10.4 D-09 (FIX-58): открытая сессия видит изменения коллег после возврата на вкладку', async () => {
  console.log('D-09: обновились по возврату на вкладку:', refreshedOnFocus.join(' | ') || 'нет (экран не устаревал)');
  console.log('D-09: остались устаревшими до перезагрузки:', staleViews.join(' | ') || 'нет');
  expect(staleViews, 'экраны, потребовавшие перезагрузки страницы').toEqual([]);
});

test('10.5 D-07 (FIX-55): роль ERP, выданная в «Команде», переживает повторный провижининг из CRM', async ({ browser }) => {
  test.setTimeout(300_000);
  const admin = await getCrmAdmin(browser);
  const info = PERSONAS.viewer;
  await admin.goto(`${ENV.crm}/users`);
  await expect(admin.locator('tr', { hasText: ENV.adminEmail })).toBeVisible();
  const sw = admin.locator('tr', { hasText: info.email }).getByRole('switch');
  // Снять доступ (с подтверждением) и выдать снова — это и есть повторный провижининг в ERP: сессии отзываются,
  // «CRM Sync» снимается и возвращается. (В прогоне раунда 1 здесь не было подтверждения, и проверка до роли не доходила.)
  await sw.click();
  await admin.getByRole('dialog').getByRole('button', { name: 'Снять доступ' }).click();
  await expect(sw).toHaveAttribute('aria-checked', 'false', { timeout: 20_000 });
  await admin.waitForTimeout(4_000);
  await sw.click();
  await expect(sw).toHaveAttribute('aria-checked', 'true', { timeout: 20_000 });
  await admin.waitForTimeout(8_000);

  const adminErp = await getSession(browser, 'admin');
  await adminErp.page.goto(`${ENV.erp}/?section=team#settings`);
  await expect(adminErp.page.getByText('Команда компании')).toBeVisible();
  const row = adminErp.page.locator('tr', { hasText: info.email }).first();
  await expect(row.getByText('Наблюдатель', { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(adminErp.page.getByText(/CRM Sync/)).toHaveCount(0);
  // Роли «Расчёт», «Финансы» и «Руководитель» (выданы так же) на месте после всех синхронизаций прогона.
  for (const p of ['calc', 'fin', 'head'] as Persona[]) {
    await expect(adminErp.page.locator('tr', { hasText: PERSONAS[p].email }).first().getByText(PERSONAS[p].erpRole!, { exact: true })).toBeVisible();
  }
  await shoot(adminErp.page, 'settings-team-after-reprovision', 'admin');
});

test('10.6 SSO CRM → ERP в чистом браузере: 10 входов из 10 без обхода; обмен без refresh_token в теле (D-01, S-14)', async ({
  browser,
}) => {
  test.setTimeout(600_000);
  const attempts = 10;
  const before = { ...ssoStats };
  let failed = 0;
  for (let i = 0; i < attempts; i++) {
    // Чистый контекст: ни cookie, ни localStorage — как первый вход человека.
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'ru-RU' });
    const page = await ctx.newPage();
    await crmLogin(page, ENV.adminEmail, ENV.adminPassword);
    await page.waitForTimeout(2_500);
    const ok = await ssoClickThrough(page);
    if (!ok) failed += 1;
    if (ok && i === 0) await shoot(page, 'sso-erp-opened', 'admin');
    await ctx.close();
    await new Promise((r) => setTimeout(r, 7_000)); // лимит обмена SSO по частоте
  }
  const stats = {
    failed: ssoStats.failed - before.failed,
    rateLimited: ssoStats.rateLimited - before.rateLimited,
    refreshInBody: ssoStats.refreshInBody - before.refreshInBody,
  };
  console.log(`SSO без обхода: неудачных входов ${failed} из ${attempts}; ждали лимит частоты: ${stats.rateLimited}; refresh в теле: ${stats.refreshInBody}`);
  test.info().annotations.push({ type: 'SSO без обхода', description: `неудачных входов ${failed} из ${attempts}` });
  expect(failed, `входов из CRM в ERP не удалось из ${attempts}`).toBe(0);
  expect(stats.refreshInBody, 'тело ответа обмена не содержит refresh_token (S-14)').toBe(0);
});

test('10.8 D-02 (новое, N-01): запись «от имени» из журнала (API) читается на экране сделки', async () => {
  test.fail(true, 'N-01: API журнала отдаёт «(от имени …)» и on_behalf_of, экран сделки печатает шаблон события без этого параметра');
  expect(onBehalfOnScreen.value, 'экран сделки показывает «от имени»').toBe(true);
});

test('10.9 D-12 (новое, N-03): имя менеджера на публичной странице КП без повтора фамилии', async () => {
  test.fail(true, 'N-03: SSO-вход пишет полное имя в first_name (accounts/services/sso.py), фамилия остаётся от провижининга — «Имя Фамилия Фамилия»');
  console.log('Имя менеджера на публичной КП:', publicManager.name);
  expect(publicManager.name.length, 'имя менеджера найдено на странице').toBeGreaterThan(0);
  expect(publicManager.name, 'имя без повтора слова').not.toMatch(/(^|\s)(\S+)\s+\2(\s|$)/);
});

test('10.7 axe: 0 нарушений serious/critical на всех кадрах ERP и публичной страницы КП (D-06)', async () => {
  writeAxeReport();
  const blocking = allBlockingAxe('erp');
  const report = JSON.parse(readFileSync(path.join(ENV.shotsDir, 'axe-results.json'), 'utf8')) as { screens: string[] };
  test.info().annotations.push({
    type: 'axe',
    description: `кадров: ${report.screens.length}; нарушений serious/critical (ERP + публичная КП): ${blocking.length}; CRM: ${allBlockingAxe('crm').length}`,
  });
  console.log(
    `axe: кадров ${report.screens.length}, serious/critical в ERP и публичной КП ${blocking.length}, в экранах CRM ${allBlockingAxe('crm').length}`,
  );
  expect(
    blocking.map((f) => `${f.screen}: ${f.id} (${f.impact}) ×${f.nodes} — ${f.target}`),
    'нарушения axe serious/critical (ERP и публичная страница КП)',
  ).toEqual([]);
});

test('10.7b axe, экраны CRM (D-06, не исправлено: FIX-58 правил ERP): label-content-name-mismatch на кнопках с aria-label', async () => {
  test.fail(true, 'D-06 (CRM): кнопки «В бэк-офис (ERP)» и иконочные кнопки с aria-label, не содержащим видимый текст — 12 кадров CRM');
  expect(allBlockingAxe('crm').map((f) => `${f.screen}: ${f.id} ×${f.nodes}`), 'нарушения axe serious/critical (экраны CRM)').toEqual([]);
});
