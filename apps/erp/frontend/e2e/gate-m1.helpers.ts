/**
 * Помощники сценария гейта M1 (FIX-50, `gate-m1.spec.ts`): сессии ролей, почта стенда, портал клиента,
 * axe и скриншоты. Только для прогона против стенда ансамбля — в CI не подключается.
 *
 * Секретов в файле нет: адреса и пароль админа CRM приходят из окружения, пароли сотрудников FIX-50
 * выпускает CRM (временный пароль → свой пароль, случайный на прогон) и живут только в памяти процесса.
 * Токены и коды из писем стенда читаются из логов в переменную процесса и не пишутся ни в вывод, ни в файлы.
 */
import AxeBuilder from '@axe-core/playwright';
import {
  expect,
  request as pwRequest,
  type APIRequestContext,
  type Browser,
  type BrowserContext,
  type Page,
} from '@playwright/test';
import { execSync } from 'node:child_process';
import { randomBytes, randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';

// ── Окружение ──────────────────────────────────────────────────────────────────

export const ENV = {
  /** ERP: `http://erp.localhost:8088` (тот же адрес, что `E2E_BASE_URL` у Playwright). */
  erp: (process.env.E2E_BASE_URL ?? '').replace(/\/$/, ''),
  /** CRM стенда: `http://crm.localhost:8088`. */
  crm: (process.env.E2E_CRM_URL ?? '').replace(/\/$/, ''),
  /** Администратор CRM этого прогона (его создаёт лид волны, пароль — только из окружения). */
  adminEmail: process.env.E2E_CRM_ADMIN_EMAIL ?? '',
  adminPassword: process.env.E2E_CRM_ADMIN_PASSWORD ?? '',
  /**
   * Команда, печатающая свежие логи `erp-backend` и `erp-worker` (письма стенда — консольный бэкенд), БЕЗ префикса
   * сервиса: `cd <корень> && docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env
   * logs --no-log-prefix --since 10m erp-backend erp-worker 2>&1`.
   */
  mailLogCmd: process.env.E2E_MAIL_LOG_CMD ?? '',
  /** Папка скриншотов; по умолчанию `docs/screens/fix-50` относительно корня репозитория. */
  shotsDir: process.env.E2E_SHOTS_DIR ?? path.resolve(process.cwd(), '../../../docs/screens/fix-50'),
  /** Необязательный файл состояния прогона (без паролей и токенов) — чтобы возобновлять с `--grep`. */
  stateFile: process.env.E2E_STATE_FILE ?? '',
};

export const gateEnabled = Boolean(ENV.erp && ENV.crm && ENV.adminEmail && ENV.adminPassword && ENV.mailLogCmd);

// ── Роли прогона ───────────────────────────────────────────────────────────────

export type Persona = 'admin' | 'head' | 'calc' | 'fin' | 'viewer';

export interface PersonaInfo {
  email: string;
  fullName: string;
  /** Роль в CRM: `admin` | `manager` | `viewer` — карта `apps/crm/backend/app/domain/erp_permissions.py`. */
  crmRole: 'Администратор' | 'Менеджер' | 'Наблюдатель';
  /** Системная роль ERP, которую админ выдаёт в «Настройки → Команда» (CRM отдаёт только manager/viewer/admin). */
  erpRole: 'Руководитель' | 'Расчёт' | 'Финансы' | 'Наблюдатель' | null;
  /** Ожидаемые права `capabilities.permissions` после выдачи роли (apps/erp/CLAUDE.md §6). */
  permissions: string[] | 'ALL';
}

export const PERSONAS: Record<Persona, PersonaInfo> = {
  admin: {
    email: ENV.adminEmail,
    fullName: 'FIX-50 Админ',
    crmRole: 'Администратор',
    erpRole: null,
    permissions: 'ALL',
  },
  head: {
    email: 'fix50-head@example.com',
    fullName: 'FIX-50 Руководитель',
    crmRole: 'Менеджер',
    erpRole: 'Руководитель',
    permissions: 'ALL',
  },
  calc: {
    email: 'fix50-calc@example.com',
    fullName: 'FIX-50 Расчётчик',
    crmRole: 'Менеджер',
    erpRole: 'Расчёт',
    permissions: [
      'contract.manage',
      'deal.manage',
      'quote.build',
      'quote.edit_pricing',
      'quote.review',
      'quote.send',
      'quote.view_cost_margin',
    ],
  },
  fin: {
    email: 'fix50-fin@example.com',
    fullName: 'FIX-50 Финансист',
    crmRole: 'Менеджер',
    erpRole: 'Финансы',
    permissions: ['data.export', 'finance.invoice', 'finance.payment', 'finance.rates', 'quote.view_cost_margin'],
  },
  viewer: {
    email: 'fix50-viewer@example.com',
    fullName: 'FIX-50 Наблюдатель',
    crmRole: 'Наблюдатель',
    erpRole: 'Наблюдатель',
    permissions: [],
  },
};

// ── Состояние прогона (в памяти; по желанию — в файле без секретов) ────────────

export interface RunState {
  run: string;
  companyName: string;
  contactName: string;
  contactEmail: string;
  leadId: number;
  dealId: number;
  quoteId: number;
  quoteNumber: string;
  contractId: number;
  invoiceId: number;
  invoiceNumber: string;
}

export function loadState(): RunState {
  const fresh: RunState = {
    run: randomBytes(3).toString('hex'),
    companyName: '',
    contactName: '',
    contactEmail: '',
    leadId: 0,
    dealId: 0,
    quoteId: 0,
    quoteNumber: '',
    contractId: 0,
    invoiceId: 0,
    invoiceNumber: '',
  };
  if (ENV.stateFile && existsSync(ENV.stateFile)) {
    try {
      return { ...fresh, ...(JSON.parse(readFileSync(ENV.stateFile, 'utf8')) as Partial<RunState>) };
    } catch {
      return fresh;
    }
  }
  return fresh;
}

export function saveState(state: RunState): void {
  if (ENV.stateFile) writeFileSync(ENV.stateFile, JSON.stringify(state, null, 2));
}

// ── Скриншоты и axe ────────────────────────────────────────────────────────────

export interface AxeFinding {
  screen: string;
  id: string;
  impact: string;
  help: string;
  nodes: number;
  target: string;
}

/** Все нарушения axe прогона (любой критичности); блокирующие — `serious` и `critical`. */
export const axeFindings: AxeFinding[] = [];
export const screenList: string[] = [];

export const WIDTHS = [
  { w: 1440, h: 900 },
  { w: 390, h: 844 },
] as const;

export function shotPath(name: string): string {
  mkdirSync(ENV.shotsDir, { recursive: true });
  return path.join(ENV.shotsDir, `${name}.png`);
}

export async function runAxe(page: Page, screen: string): Promise<AxeFinding[]> {
  const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  const found: AxeFinding[] = result.violations.map((v) => ({
    screen,
    id: v.id,
    impact: v.impact ?? 'unknown',
    help: v.help,
    nodes: v.nodes.length,
    target: String(v.nodes[0]?.target?.join(' ') ?? '').slice(0, 160),
  }));
  axeFindings.push(...found);
  return found;
}

/**
 * Экран `<экран>-<роль>-<ширина>.png` на 1440 и 390 px + axe (в браузере: контраст считается по факту).
 * Возвращает размер до и оставляет вьюпорт 1440. Адреса в кадр не попадают (скриншот страницы, без адресной строки).
 */
export async function shoot(
  page: Page,
  screen: string,
  role: string,
  opts: { axe?: boolean; fullPage?: boolean; settleMs?: number } = {},
): Promise<void> {
  const { axe = true, fullPage = true, settleMs = 700 } = opts;
  for (const { w, h } of WIDTHS) {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(settleMs);
    const name = `${screen}-${role}-${w}`;
    await page.screenshot({ path: shotPath(name), fullPage });
    screenList.push(name);
    if (axe) await runAxe(page, name);
  }
  await page.setViewportSize({ width: WIDTHS[0].w, height: WIDTHS[0].h });
  await page.waitForTimeout(300);
}

/**
 * Диалог или шторка: смена ширины перемонтирует экран и закрывает их, поэтому на каждой ширине диалог открывается
 * заново (`open`), снимается кадр, затем Escape.
 */
export const mobileUnreachable: string[] = [];

export async function shootDialog(page: Page, screen: string, role: string, open: () => Promise<void>): Promise<void> {
  for (const { w, h } of WIDTHS) {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(700);
    const name = `${screen}-${role}-${w}`;
    page.setDefaultTimeout(8_000);
    try {
      await open();
    } catch {
      // Элемент, открывающий диалог, на этой ширине недоступен — это находка прогона, а не повод остановить сценарий.
      mobileUnreachable.push(name);
      page.setDefaultTimeout(0);
      continue;
    }
    page.setDefaultTimeout(0);
    await page.waitForTimeout(700);
    await page.screenshot({ path: shotPath(name), fullPage: false });
    screenList.push(name);
    await runAxe(page, name);
    await closeDialogs(page);
  }
  await page.setViewportSize({ width: WIDTHS[0].w, height: WIDTHS[0].h });
  await page.waitForTimeout(400);
  await closeDialogs(page);
}

/** Закрывает диалоги и шторки: Escape, затем кнопка «Close»; пока что-то открыто — повторяет. */
export async function closeDialogs(page: Page): Promise<void> {
  for (let i = 0; i < 4; i++) {
    await page.keyboard.press('Escape');
    await page.waitForTimeout(500);
    if (!(await page.getByRole('dialog').count())) return;
    const close = page.getByRole('dialog').getByRole('button', { name: /^(Close|Закрыть)$/ });
    if (await close.count()) await close.first().click().catch(() => undefined);
    await page.waitForTimeout(500);
  }
}

export function blockingAxe(): AxeFinding[] {
  return axeFindings.filter((f) => f.impact === 'serious' || f.impact === 'critical');
}

interface AxeReportFile {
  screens: string[];
  unreachable_dialogs: string[];
  violations: AxeFinding[];
}

function readAxeReport(): AxeReportFile {
  const file = path.join(ENV.shotsDir, 'axe-results.json');
  if (!existsSync(file)) return { screens: [], unreachable_dialogs: [], violations: [] };
  try {
    const old = JSON.parse(readFileSync(file, 'utf8')) as Partial<AxeReportFile>;
    return { screens: old.screens ?? [], unreachable_dialogs: old.unreachable_dialogs ?? [], violations: old.violations ?? [] };
  } catch {
    return { screens: [], unreachable_dialogs: [], violations: [] };
  }
}

/** Отчёт axe: результаты этого процесса поверх прежних (возобновлённые прогоны с `--grep` не теряют кадры). */
export function writeAxeReport(): void {
  mkdirSync(ENV.shotsDir, { recursive: true });
  const old = readAxeReport();
  const fresh = new Set([...screenList, ...mobileUnreachable]);
  const report = {
    generated_by: 'apps/erp/frontend/e2e/gate-m1.spec.ts',
    tags: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'],
    screens: [...new Set([...old.screens.filter((s) => !fresh.has(s)), ...screenList])].sort(),
    unreachable_dialogs: [...new Set([...old.unreachable_dialogs.filter((s) => !fresh.has(s)), ...mobileUnreachable])].sort(),
    violations: [...old.violations.filter((v) => !fresh.has(v.screen)), ...axeFindings],
  };
  writeFileSync(path.join(ENV.shotsDir, 'axe-results.json'), JSON.stringify(report, null, 2));
}

/** Нарушения axe по всему отчёту (включая прежние процессы) — для итогового теста. */
export function allBlockingAxe(): AxeFinding[] {
  return readAxeReport().violations.filter((f) => f.impact === 'serious' || f.impact === 'critical');
}

// ── Почта стенда (консольный бэкенд) ───────────────────────────────────────────

/** Тексты писем из логов: `text/plain` приходит base64-блоками. Свежие — в конце. */
export function mailTexts(): string[] {
  const raw = execSync(ENV.mailLogCmd, { encoding: 'utf8', maxBuffer: 256 * 1024 * 1024, shell: '/bin/bash' });
  const blocks = [...raw.matchAll(/Content-Transfer-Encoding: base64\s*\n\s*\n((?:[A-Za-z0-9+/=]{4,}\s*\n)+)/g)];
  return blocks.map((m) => Buffer.from(m[1].replace(/\s+/g, ''), 'base64').toString('utf8'));
}

/** Ждёт письмо, где есть все подстроки `needles` и совпадает `pick`; возвращает группу 1. Значение — только в память. */
export async function waitMail(needles: string[], pick: RegExp, timeoutMs = 45_000): Promise<string> {
  const until = Date.now() + timeoutMs;
  for (;;) {
    for (const text of mailTexts().reverse()) {
      if (!needles.every((n) => text.includes(n))) continue;
      const m = pick.exec(text);
      if (m) return m[1];
    }
    if (Date.now() > until) throw new Error(`письмо не пришло: ${needles.join(' + ')}`);
    await new Promise((r) => setTimeout(r, 2_000));
  }
}

// ── CRM: вход, пользователи ────────────────────────────────────────────────────

export function newPassword(): string {
  return `Fx50-${randomBytes(6).toString('hex')}A1`;
}

/** Вход в CRM; если стоит временный пароль — задаёт свой. Возвращает действующий пароль. */
export async function crmLogin(page: Page, email: string, password: string): Promise<string> {
  await page.goto(`${ENV.crm}/login`);
  await page.getByLabel(/e-?mail|почта/i).fill(email);
  await page.getByLabel(/парол/i).first().fill(password);
  await page.getByRole('button', { name: /войти/i }).click();
  await page.waitForURL(/\/(inbox|dashboard|change-password|leads|clients)/, { timeout: 30_000 });
  let current = password;
  if (/change-password/.test(page.url())) {
    current = newPassword();
    await page.getByLabel('Текущий пароль').fill(password);
    await page.getByLabel('Новый пароль').fill(current);
    await page.getByLabel('Повторите пароль').fill(current);
    await page.getByRole('button', { name: 'Сохранить' }).click();
    await page.waitForURL((u) => !/change-password/.test(u.pathname), { timeout: 30_000 });
  }
  return current;
}

async function readTempPassword(page: Page): Promise<string> {
  const code = page.getByRole('dialog').locator('code').first();
  await expect(code).toBeVisible();
  const value = (await code.innerText()).trim();
  await page.getByRole('dialog').getByRole('button', { name: /Готово|Done/ }).click();
  return value;
}

/**
 * Сотрудник из CRM «Пользователи»: создать (если нет) или сбросить пароль, включить «Доступ к ERP».
 * Возвращает временный пароль (в память). Роль ERP потом выдаёт админ в «Настройки → Команда».
 */
export async function ensureCrmUser(adminPage: Page, p: PersonaInfo): Promise<string> {
  await adminPage.goto(`${ENV.crm}/users`);
  await expect(adminPage.getByRole('heading', { name: 'Пользователи' })).toBeVisible();
  await expect(adminPage.locator('tr', { hasText: ENV.adminEmail })).toBeVisible();
  const row = adminPage.locator('tr', { hasText: p.email });
  let temp: string;
  if (await row.count()) {
    await row.getByRole('button').last().click();
    await adminPage.getByRole('menuitem', { name: 'Сбросить пароль', exact: true }).click();
    await adminPage.getByRole('dialog').getByRole('button', { name: 'Сбросить', exact: true }).click();
    temp = await readTempPassword(adminPage);
  } else {
    await adminPage.getByRole('button', { name: 'Новый пользователь' }).click();
    const dlg = adminPage.getByRole('dialog');
    await dlg.getByLabel(/e-?mail/i).fill(p.email);
    await dlg.getByLabel(/Имя/).first().fill(p.fullName);
    if (p.crmRole !== 'Менеджер') {
      await dlg.locator('.ant-select-selection-item-remove').click();
      await dlg.locator('.ant-select').click();
      await adminPage.locator('.ant-select-item-option', { hasText: p.crmRole }).click();
      await adminPage.keyboard.press('Escape');
    }
    await dlg.getByRole('button', { name: 'Создать пользователя' }).click();
    temp = await readTempPassword(adminPage);
  }
  const sw = adminPage.locator('tr', { hasText: p.email }).getByRole('switch');
  if ((await sw.getAttribute('aria-checked')) !== 'true') {
    await sw.click();
    await expect(sw).toHaveAttribute('aria-checked', 'true');
  }
  return temp;
}

// ── ERP: вход из CRM по SSO ────────────────────────────────────────────────────

export interface Session {
  persona: Persona;
  ctx: BrowserContext;
  page: Page;
}

/**
 * Вход в ERP через «В бэк-офис (ERP)» в CRM. Штатный обмен токена ломается (дефект D-01: фоновый 401 `/me/`
 * уводит страницу `/sso/exchange` на `/` и обрывает POST обмена), поэтому обход: токен берётся из перехваченного
 * запроса SPA, обмен делает `ctx.request` (cookie общая с браузером). Токен — только в переменную процесса.
 * Обмен ограничен по частоте (429 «available in N seconds») — ждём и повторяем.
 */
export async function ssoToErp(ctx: BrowserContext, crmPage: Page): Promise<void> {
  let token = '';
  await crmPage.route('**/api/v1/auth/sso/exchange/', async (route) => {
    token = (route.request().postDataJSON() as { token: string }).token;
    await route.abort();
  });
  await crmPage.getByRole('button', { name: /ERP/ }).first().click();
  await crmPage.waitForURL(/sso\/exchange/, { timeout: 30_000 });
  await expect.poll(() => token, { timeout: 10_000 }).not.toBe('');
  const url = `${ENV.erp}/api/v1/auth/sso/exchange/`;
  let res = await ctx.request.post(url, { data: { token } });
  for (let i = 0; i < 10 && res.status() === 429; i++) {
    const m = /in (\d+) second/.exec(await res.text());
    await crmPage.waitForTimeout(((m ? Number(m[1]) : 6) + 2) * 1000);
    res = await ctx.request.post(url, { data: { token } });
  }
  expect(res.status(), 'обмен SSO-токена на сессию ERP').toBe(200);
  await crmPage.unroute('**/api/v1/auth/sso/exchange/');
}

export async function openErpSession(
  browser: Browser,
  persona: Persona,
  password: string,
): Promise<{ session: Session; crmPassword: string }> {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    locale: 'ru-RU',
    baseURL: ENV.erp,
  });
  const page = await ctx.newPage();
  const crmPassword = await crmLogin(page, PERSONAS[persona].email, password);
  await ssoToErp(ctx, page);
  // Обновление сессии по cookie тоже ограничено по частоте (429) — при форме входа ждём и перезагружаем.
  for (let i = 0; i < 6; i++) {
    await page.goto(`${ENV.erp}/`);
    const ok = await page
      .getByText('Дашборд')
      .first()
      .waitFor({ state: 'visible', timeout: 15_000 })
      .then(() => true)
      .catch(() => false);
    if (ok) break;
    await page.waitForTimeout(12_000);
  }
  await expect(page.getByText('Дашборд').first()).toBeVisible({ timeout: 5_000 });
  return { session: { persona, ctx, page }, crmPassword };
}

const accessCache = new WeakMap<BrowserContext, { token: string; at: number }>();

/**
 * Access-токен ERP по cookie сессии (только для проб API ролей; в память, на 10 минут). `refresh` ограничен по
 * частоте (429) — токен кэшируется, при 429 ждём.
 */
export async function apiHeaders(ctx: BrowserContext): Promise<Record<string, string>> {
  const cached = accessCache.get(ctx);
  if (cached && Date.now() - cached.at < 10 * 60_000) return { Authorization: `Bearer ${cached.token}` };
  let res = await ctx.request.post(`${ENV.erp}/api/v1/auth/token/refresh/`);
  for (let i = 0; i < 10 && res.status() === 429; i++) {
    await new Promise((r) => setTimeout(r, 8_000));
    res = await ctx.request.post(`${ENV.erp}/api/v1/auth/token/refresh/`);
  }
  expect(res.status(), 'refresh access-токена ERP').toBe(200);
  const { access } = (await res.json()) as { access: string };
  accessCache.set(ctx, { token: access, at: Date.now() });
  return { Authorization: `Bearer ${access}` };
}

export async function erpGet<T = unknown>(ctx: BrowserContext, apiPath: string): Promise<T> {
  const res = await ctx.request.get(`${ENV.erp}/api/v1/${apiPath}`, { headers: await apiHeaders(ctx) });
  expect(res.status(), `GET ${apiPath}`).toBe(200);
  return (await res.json()) as T;
}

/** Проба мутации под ролью: возвращает статус и `detail` (тело не логируется). */
export async function probe(
  ctx: BrowserContext,
  method: 'post' | 'patch' | 'delete',
  apiPath: string,
  data?: unknown,
): Promise<{ status: number; detail: string }> {
  const res = await ctx.request[method](`${ENV.erp}/api/v1/${apiPath}`, {
    headers: await apiHeaders(ctx),
    data,
  });
  let detail = '';
  try {
    detail = String(((await res.json()) as { detail?: unknown }).detail ?? '');
  } catch {
    /* тело не JSON */
  }
  return { status: res.status(), detail };
}

// ── Портал клиента (Cabinet API) — шаги клиента, UI Cabinet — зона FIX-51 ─────

export interface PortalClient {
  api: APIRequestContext;
  idem: () => Record<string, string>;
}

/** Вход клиента по magic-link из письма (в письме ищется имя контакта прогона). Лимит — 5 ссылок/час на e-mail. */
export async function portalLogin(email: string, contactName: string): Promise<PortalClient> {
  const api = await pwRequest.newContext({
    baseURL: ENV.erp,
    extraHTTPHeaders: { 'Content-Type': 'application/json' },
  });
  const idem = () => ({ 'Idempotency-Key': randomUUID() });
  const req = await api.post('/api/portal/v1/auth/magic-link', { data: { email }, headers: idem() });
  expect(req.status(), 'запрос magic-link клиента').toBe(200);
  const token = await waitMail([contactName], /auth\/magic#token=([A-Za-z0-9_-]+)/);
  const ex = await api.post('/api/portal/v1/auth/magic', { data: { token }, headers: idem() });
  expect(ex.status(), 'обмен magic-link клиента').toBe(200);
  return { api, idem };
}

export async function portalGet<T = unknown>(c: PortalClient, apiPath: string): Promise<{ status: number; body: T }> {
  const res = await c.api.get(`/api/portal/v1/${apiPath}`);
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* не JSON */
  }
  return { status: res.status(), body: body as T };
}

export async function portalPost<T = unknown>(
  c: PortalClient,
  apiPath: string,
  data: unknown = {},
): Promise<{ status: number; body: T }> {
  const res = await c.api.post(`/api/portal/v1/${apiPath}`, { data, headers: c.idem() });
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* не JSON */
  }
  return { status: res.status(), body: body as T };
}

// ── Мелочи интерфейса ──────────────────────────────────────────────────────────

/** Подпись показанного тоста (sonner) — для отчёта; без токенов. */
export async function lastToast(page: Page): Promise<string> {
  const t = page.locator('[data-sonner-toast]').last();
  try {
    await t.waitFor({ state: 'visible', timeout: 4_000 });
    return (await t.innerText()).replace(/\s+/g, ' ').trim();
  } catch {
    return '';
  }
}

/** Числа вида `12 055,90` / `1 944 375,55 UZS` → строка для Decimal. */
export function toDecimalString(text: string): string {
  return text
    .replace(/[^\d,.-]/g, '')
    .replace(',', '.');
}
