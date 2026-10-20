/**
 * Гейт M1 (FIX-50): прогон пути бэк-офиса BUSINESS §4–§11 на СТЕНДЕ ансамбля — настоящие CRM и ERP, без моков.
 *
 *   заявка (CRM → «Передать в бэк-офис») → КП (строки, курс, маржа) → согласование (цепочка ролей) → отправка
 *   клиенту → публичная ссылка и акцепт → договор → счёт и оплата → поставка → акт
 *
 * Роли: «Руководитель» (роль HEAD), «Расчёт», «Финансы», «Наблюдатель» и Администратор CRM (= суперпользователь
 * ERP). Сотрудников заводит CRM («Пользователи» → «Доступ к ERP», FIX-11), системную роль ERP выдаёт админ в
 * «Настройки → Команда». Клиент — публичная страница КП (браузер) и портал (шаги клиента по API; UI Cabinet — FIX-51).
 *
 * НЕ запускается в CI и по умолчанию: без переменных окружения весь файл пропускается. Запуск (из apps/erp/frontend):
 *
 *   E2E_BASE_URL=http://erp.localhost:8088 E2E_CRM_URL=http://crm.localhost:8088 \
 *   E2E_CRM_ADMIN_EMAIL=… E2E_CRM_ADMIN_PASSWORD=… \
 *   E2E_MAIL_LOG_CMD='cd <корень> && docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env \
 *                     logs --no-log-prefix --since 10m erp-backend erp-worker 2>&1' \
 *   npx playwright test e2e/gate-m1.spec.ts --workers=1
 *
 * Скриншоты (1440 и 390 px) и `axe-results.json` пишутся в `docs/screens/fix-50/` (или `E2E_SHOTS_DIR`).
 *
 * Известные дефекты прогона (docs/runbooks/m1_qa_02_report.md) помечены `test.fail()`: пока дефект жив, тест «красный
 * как ожидалось» и набор зелёный; когда дефект исправлен, тест «неожиданно прошёл» — аннотацию снимают, это повтор гейта.
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
  shoot,
  shootDialog,
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
const immutabilityProbe: Record<string, number> = {};
const staleViews: string[] = [];
const dupRef = { status: 0, returnedAmount: '', paidAfter: '' };

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

/** Ждёт элемент; если открытая сессия его не показывает (устаревший кэш SPA, D-09) — фиксирует и перезагружает страницу. */
async function visibleOrReload(page: Page, target: ReturnType<Page['locator']>, label: string): Promise<void> {
  const ok = await target
    .waitFor({ state: 'visible', timeout: 6_000 })
    .then(() => true)
    .catch(() => false);
  if (ok) return;
  staleViews.push(label);
  await page.reload();
  await expect(target).toBeVisible({ timeout: 20_000 });
}

async function goErp(page: Page, hash: string): Promise<void> {
  await page.goto(`${ENV.erp}/#${hash}`);
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

// Проба «позиции КП изменяемы?» — правка заметки позиции, на суммы не влияет.
async function probeQuoteItemMutation(ctx: BrowserContext, label: string): Promise<number> {
  const q = await quoteJson(ctx);
  const item = (q.items as Json[])[0];
  const res = await probe(ctx, 'patch', `crm/quote-items/${item.id}/`, { note: `FIX-50 проба изменения (${label})` });
  immutabilityProbe[label] = res.status;
  return res.status;
}

test.beforeAll(() => {
  if (!S.companyName) {
    S.companyName = `FIX-50 Тест ООО ${S.run}`;
    S.contactName = `FIX-50 Клиент ${S.run}`;
    S.contactEmail = `fix50-lead-${S.run}@example.com`;
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

test('0.3 ERP «Настройки → Команда»: админ выдаёт системные роли; права по `/me` = каталог ролей (CLAUDE.md §6)', async ({
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
    const want = [info.erpRole!, `CRM Sync: ${info.email}`];
    for (const role of want) {
      await row.getByRole('button', { name: /Выбрать роли|Расчёт|Финансы|Руководитель|Наблюдатель|CRM Sync/ }).last().click();
      const item = admin.page.getByRole('menuitemcheckbox', { name: role, exact: true });
      const checked = (await item.getAttribute('aria-checked')) === 'true';
      const shouldBeChecked = role === info.erpRole;
      if (checked !== shouldBeChecked) await item.click();
      await closeDialogs(admin.page);
      await admin.page.waitForTimeout(600);
    }
  }
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
        text: `FIX-50 (${S.run}): рельсовые скрепления КБ-65 — 200 комплектов; шефмонтаж — 1 услуга. КП до пятницы.`,
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

  await addQuoteLine(calc.page, 'Скрепление рельсовое КБ-65 FIX-50', '200', '120');
  await addQuoteLine(calc.page, 'Шефмонтаж FIX-50 (услуга)', '1', '1500');
  await expect(calc.page.getByText('Позиций: 2')).toBeVisible();

  const q = await quoteJson(calc.ctx);
  expect(q.items).toHaveLength(2);
  expect(money(q.total_incl_vat).gt(0), 'итог КП посчитан').toBe(true);
  // Наценка 20 % на себестоимость → маржа 16,67 % (порог 15 %).
  expect(Math.abs(Number(q.economics?.gross_margin_percent ?? q.margin_percent) - 16.67)).toBeLessThan(0.1);
  await shoot(calc.page, 'quote-builder-draft', 'calc');

  // «Расчёт» договорной курс не меняет — кнопки нет, сервер отказывает.
  await expect(calc.page.getByRole('button', { name: 'Изменить курс' })).toHaveCount(0);
  const denied = await probe(calc.ctx, 'post', `crm/quotes/${S.quoteId}/fx-override/`, { rate: '12500', reason: 'FIX-50' });
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
  await fx.last().fill('FIX-50: курс по договору с клиентом');
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
  await probeQuoteItemMutation(calc.ctx, 'на согласовании');

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

test('3.2 D-02: «Расчёт» согласует собственное КП (автор и согласующий — один человек)', async ({ browser }) => {
  test.fail(true, 'D-02: в цепочке есть место автора, и «Согласовать» на нём нажимается — разделения обязанностей нет');
  const calc = await getSession(browser, 'calc');
  await goErp(calc.page, `deal-quote/${S.dealId}`);
  await calc.page.getByRole('button', { name: 'Открыть панель согласования' }).click({ force: true });
  const dlg = calc.page.getByRole('dialog');
  const ownRow = dlg
    .getByText(PERSONAS.calc.fullName, { exact: true })
    .locator('xpath=ancestor::*[.//button[normalize-space()="Согласовать"]][1]');
  const act = calc.page.waitForResponse((r) => r.url().includes('/approval-act/'));
  await ownRow.getByRole('button', { name: 'Согласовать' }).click();
  const status = (await act).status();
  console.log('D-02: ответ approval-act на собственный шаг автора:', status);
  // Ожидание: свой шаг автору не отдают (403/400). Факт: 200.
  expect(status).toBeGreaterThanOrEqual(400);
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
  await probeQuoteItemMutation(calc.ctx, 'утверждено, до отправки');
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

test('4.2 D-03: у «Наблюдателя» на экранах сделки и КП видны кнопки действий (нужно: скрыты)', async ({ browser }) => {
  test.fail(true, 'D-03: кнопки «Взять в работу», «К подбору», «Создать документ», «Добавить», «Удалить позицию» видны роли без прав');
  const v = await getSession(browser, 'viewer');
  await goErp(v.page, dealHash());
  const actions = ['Взять в работу', 'К подбору', 'Создать документ', 'Вернуть в очередь'];
  const shown: string[] = [];
  for (const name of actions) {
    if (await v.page.getByRole('button', { name, exact: true }).count()) shown.push(name);
  }
  await goErp(v.page, `deal-quote/${S.dealId}`);
  for (const name of ['Добавить', 'Сохранить', 'Экспорт', 'Создать договор']) {
    if (await v.page.getByRole('button', { name, exact: true }).count()) shown.push(name);
  }
  console.log('D-03: кнопки действий, видимые Наблюдателю:', shown.join(', ') || 'нет');
  expect(shown, 'кнопки действий, видимые Наблюдателю').toEqual([]);
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
    // D-09: у автора КП открытая сессия показывает прежний статус (согласование прошёл другой человек) — до перезагрузки.
    staleViews.push('КП: «Отправить КП» после согласования другим сотрудником');
    await calc.page.reload();
  }
  const openSend = async () => {
    await calc.page.getByRole('button', { name: 'Отправить КП' }).first().click();
  };
  await shootDialog(calc.page, 'quote-send-dialog', 'calc', openSend);
  await openSend();
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
  await probeQuoteItemMutation(calc.ctx, 'отправлено клиенту');
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
  await expect(page.getByRole('button', { name: /Принять предложение/ })).toBeVisible();
  await shoot(page, 'public-quote', 'client');

  const pdf = await ctx.request.get(link);
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()['content-type']).toContain('application/pdf');
  expect((await pdf.body()).subarray(0, 5).toString()).toBe('%PDF-');

  const stranger = await ctx.request.get(`${ENV.erp}/api/v1/public/quotes/fix50-no-such-token-0000000000/`, {
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

  const code = await waitMail([S.quoteNumber], /Ваш код:\s*(\d{4,12})/);
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
  await probeQuoteItemMutation(calc.ctx, 'принято клиентом');
});

test('5.4 D-04 (P0): после отправки и акцепта позиции КП можно менять — клиент видит другую сумму', async ({
  browser,
}) => {
  test.fail(true, 'D-04 (P0): PATCH/POST crm/quote-items на SENT и APPROVED КП проходит (200/201), публичная страница показывает новую сумму');
  console.log('D-04: статусы правки позиции КП по этапам:', JSON.stringify(immutabilityProbe));
  const calc = await getSession(browser, 'calc');
  expect(immutabilityProbe['отправлено клиенту'], 'правка позиции отправленного КП').toBeGreaterThanOrEqual(400);
  expect(immutabilityProbe['принято клиентом'], 'правка позиции принятого КП').toBeGreaterThanOrEqual(400);
  void calc;
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
      // D-09: список счетов в кэше SPA устарел (запрошен до создания счёта) — шторка не открывается до перезагрузки.
      staleViews.push('Счета: шторка счёта после создания счёта другим сотрудником');
      await goErp(fin.page, dealHash());
      await fin.page.reload();
      await fin.page.getByRole('button', { name: 'Открыть счёт' }).click();
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
      reference: `FIX-50 сверх остатка ${S.run}`,
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
  const advanceRef = `FIX-50 аванс ${S.run}`;
  await pay('100000000', advanceRef);
  let inv = await erpGet<Json>(fin.ctx, `crm/invoices/${S.invoiceId}/`);
  expect(money(inv.amount_paid).toFixed(2)).toBe('100000000.00');
  expect(inv.status).toBe('PARTIAL');
  await shoot(fin.page, 'payments', 'fin');

  // Тот же банковский референс, другая сумма: платёж обязан либо записаться, либо быть отклонён (D-05).
  const dup = await fin.ctx.request.post(`${ENV.erp}/api/v1/crm/invoices/${S.invoiceId}/record-payment/`, {
    headers: await apiHeaders(fin.ctx),
    data: { amount: '1000.00', paid_at: today, reference: advanceRef },
  });
  dupRef.status = dup.status();
  dupRef.returnedAmount = dup.status() === 201 ? money(((await dup.json()) as Json).amount).toFixed(2) : '';
  inv = await erpGet<Json>(fin.ctx, `crm/invoices/${S.invoiceId}/`);
  dupRef.paidAfter = money(inv.amount_paid).toFixed(2);
  console.log('D-05: повтор референса — ответ', dupRef.status, 'сумма в ответе', dupRef.returnedAmount, 'оплачено после', dupRef.paidAfter);

  // Остаток считаем по факту счёта (если бы 1000 записались, доплата уменьшилась бы).
  const rest = money(inv.total_incl_vat).minus(money(inv.amount_paid)).toFixed(2);
  await pay(rest, `FIX-50 доплата ${S.run}`);
  inv = await erpGet<Json>(fin.ctx, `crm/invoices/${S.invoiceId}/`);
  expect(money(inv.amount_paid).toFixed(2)).toBe('428400000.00');
  expect(inv.status).toBe('PAID');
  // Закрытый счёт новых платежей не принимает.
  expect(
    await probe(fin.ctx, 'post', `crm/invoices/${S.invoiceId}/record-payment/`, {
      amount: '1.00',
      paid_at: today,
      reference: `FIX-50 после закрытия ${S.run}`,
    }),
  ).toMatchObject({ status: 400, detail: 'INVOICE_ALREADY_PAID' });
});

test('7.3 D-05: повторный платёж с тем же референсом и другой суммой молча «принимается» без записи', async () => {
  test.fail(true, 'D-05: record-payment с совпавшим референсом возвращает 201 и прежний платёж — присланная сумма теряется');
  expect(dupRef.status, 'шаг 7.2 выполнен').toBeGreaterThan(0);
  // Допустимо: отказ (4xx) или запись присланной суммы. Недопустимо: 201 с прежним платежом.
  const rejected = dupRef.status >= 400;
  const recorded = dupRef.status === 201 && dupRef.returnedAmount === '1000.00' && dupRef.paidAfter === '100001000.00';
  expect(rejected || recorded, `ответ ${dupRef.status}, сумма в ответе ${dupRef.returnedAmount}, оплачено ${dupRef.paidAfter}`).toBe(true);
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
      await d.getByLabel('Перевозчик').fill('FIX-50 Логистика');
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
  const mine = lines.body.filter((l) => l.status === 'delivered' && /FIX-50/.test(l.title));
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
    ['viewer', 'post', 'crm/quote-items/', { quote: S.quoteId, title: 'FIX-50 проба', quantity: 1, unit_cost: '1' }],
    ['viewer', 'post', `crm/quotes/${S.quoteId}/send-to-client/`, {}],
    ['viewer', 'post', `crm/quotes/${S.quoteId}/fx-override/`, { rate: '12500', reason: 'FIX-50' }],
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
    ['fin', 'post', 'crm/quote-items/', { quote: S.quoteId, title: 'FIX-50 проба', quantity: 1, unit_cost: '1' }],
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

// ═══ 10. Итоги ═════════════════════════════════════════════════════════════════

test('10.1 axe: 0 нарушений serious/critical на ключевых экранах (D-06)', async () => {
  writeAxeReport();
  const blocking = allBlockingAxe();
  const report = JSON.parse(readFileSync(path.join(ENV.shotsDir, 'axe-results.json'), 'utf8')) as { screens: string[] };
  test.info().annotations.push({
    type: 'axe',
    description: `кадров: ${report.screens.length}; нарушений serious/critical: ${blocking.length}`,
  });
  console.log(`axe: кадров ${report.screens.length}, нарушений serious/critical ${blocking.length}`);
  if (blocking.length) test.fail(true, `D-06: axe нашёл ${blocking.length} нарушений serious/critical — см. axe-results.json и отчёт`);
  expect(
    blocking.map((f) => `${f.screen}: ${f.id} (${f.impact}) ×${f.nodes} — ${f.target}`),
    'нарушения axe serious/critical',
  ).toEqual([]);
});

test('10.2 D-07: повторный провижининг CRM сбрасывает роль ERP, выданную админом в «Команде»', async ({ browser }) => {
  test.fail(true, 'D-07: provision_crm_user делает member.company_roles.set([crm_role]) — роли ERP затираются при любой синхронизации');
  test.setTimeout(300_000);
  const admin = await getCrmAdmin(browser);
  const info = PERSONAS.viewer;
  await admin.goto(`${ENV.crm}/users`);
  await expect(admin.locator('tr', { hasText: ENV.adminEmail })).toBeVisible();
  const sw = admin.locator('tr', { hasText: info.email }).getByRole('switch');
  await sw.click();
  await expect(sw).toHaveAttribute('aria-checked', 'false');
  // Подтверждение снятия доступа.
  const confirm = admin.getByRole('button', { name: 'Снять доступ' });
  if (await confirm.count()) await confirm.click();
  await sw.click();
  await expect(sw).toHaveAttribute('aria-checked', 'true');
  await admin.waitForTimeout(8_000);

  const adminErp = await getSession(browser, 'admin');
  await adminErp.page.goto(`${ENV.erp}/?section=team#settings`);
  await expect(adminErp.page.getByText('Команда компании')).toBeVisible();
  const row = adminErp.page.locator('tr', { hasText: info.email }).first();
  // Ожидание: роль «Наблюдатель» осталась. Факт: только «CRM Sync: …».
  await expect(row.getByText('Наблюдатель', { exact: true })).toBeVisible();
});

test('10.3 SSO CRM → ERP без обхода: 10 входов подряд (D-01: гонка — обмен токена обрывается редиректом `/sso/exchange` → `/`)', async ({
  browser,
}) => {
  // D-01 плавающий: при разведке вход не удавался в 5 из 5 попыток, позже в 2 из 8, в итоговом прогоне — 0 из 10. Тест строгий.
  test.setTimeout(480_000);
  const attempts = 10;
  let failed = 0;
  for (let i = 0; i < attempts; i++) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'ru-RU' });
    const page = await ctx.newPage();
    await crmLogin(page, ENV.adminEmail, ENV.adminPassword);
    await page.waitForTimeout(2_500);
    await page.getByRole('button', { name: /ERP/ }).first().click();
    // Штатный путь должен привести в рабочее место ERP; в дефекте — на форму входа «Вход в кабинет».
    const ok = await page
      .getByText('Дашборд')
      .first()
      .waitFor({ state: 'visible', timeout: 10_000 })
      .then(() => true)
      .catch(() => false);
    if (!ok) failed += 1;
    await ctx.close();
    await new Promise((r) => setTimeout(r, 7_000)); // лимит обмена SSO по частоте
  }
  console.log(`SSO без обхода: неудачных входов ${failed} из ${attempts}`);
  test.info().annotations.push({ type: 'SSO без обхода', description: `неудачных входов ${failed} из ${attempts}` });
  expect(failed, `входов из CRM в ERP не удалось из ${attempts}`).toBe(0);
});

test('10.4 D-09: открытая сессия не видит изменений, сделанных другими сотрудниками, до перезагрузки', async () => {
  test.fail(true, 'D-09: кэш SPA не обновляется — статус КП и список счетов у открытой сессии устарели (нужна перезагрузка страницы)');
  console.log('D-09: устаревшие представления:', staleViews.join(' | ') || 'нет');
  expect(staleViews, 'экраны, потребовавшие перезагрузки').toEqual([]);
});
