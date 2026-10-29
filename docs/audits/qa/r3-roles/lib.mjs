// R-3: общие помощники сценариев «роль-универсал» против живого стенда (не MSW). Не входит в `make check-platform`.
// Playwright, axe и yaml берутся из зависимостей `apps/platform/web` (node_modules рядом с кодом web, ничего не ставим).
// Ожидания строятся из каталога `packages/contracts/platform-rbac.yaml` (v2), а не из кода web.
import { createRequire } from "node:module";
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
export const ROOT = resolve(here, "../../../..");
const req = createRequire(resolve(ROOT, "apps/platform/web/package.json"));
export const { chromium } = req("@playwright/test");
export const AxeBuilder = req("@axe-core/playwright").default ?? req("@axe-core/playwright");
const yaml = req("yaml");

export const BASE = process.env.QA_BASE ?? "http://platform.localhost:18090";
export const CRM = process.env.QA_CRM ?? "http://crm.localhost:18090";
export const SHOTS = process.env.QA_SHOTS ?? resolve(ROOT, "docs/screens/r3-roles");
export const OUT = process.env.QA_OUT;
if (!OUT) throw new Error("QA_OUT не задан: каталог результатов вне репозитория");
mkdirSync(SHOTS, { recursive: true });
mkdirSync(OUT, { recursive: true });

/** Учётные данные и состояние стенда: файлы KEY=VALUE и JSON вне репозитория (QA_CREDS, QA_OUT/state.json). */
export function creds() {
  const file = process.env.QA_CREDS;
  if (!file) throw new Error("QA_CREDS не задан: файл KEY=VALUE вне репозитория");
  return Object.fromEntries(
    readFileSync(file, "utf8").trim().split("\n").filter((l) => l.includes("=")).map((l) => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1)]),
  );
}
export function setCred(key, value) {
  const file = process.env.QA_CREDS;
  const c = creds();
  c[key] = value;
  writeFileSync(file, Object.entries(c).map(([k, v]) => `${k}=${v}`).join("\n") + "\n", { mode: 0o600 });
}
const STATE = resolve(OUT, "state.json");
export function state() {
  return existsSync(STATE) ? JSON.parse(readFileSync(STATE, "utf8")) : {};
}
export function setState(patch) {
  writeFileSync(STATE, JSON.stringify({ ...state(), ...patch }, null, 2));
}

// --- каталог -------------------------------------------------------------------------------------------------------
export const catalog = yaml.parse(readFileSync(resolve(ROOT, "packages/contracts/platform-rbac.yaml"), "utf8"));
const labels = JSON.parse(readFileSync(resolve(ROOT, "apps/platform/web/src/shared/i18n/ru/modules.json"), "utf8"));
const RANK = { hidden: 0, read: 1, full: 2 };
const MODULE_ORDER = ["dashboard", "crm", "eds", "erp", "chats", "admin"];
export const MODULE_TITLES = { dashboard: "Dashboard", crm: "CRM", eds: "EDS", erp: "ERP", chats: "Chats", admin: "Admin" };
const resByKey = Object.fromEntries(catalog.resources.map((r) => [r.key, r]));

/** Пути разделов (SPEC-v3 §6.2, модули web): ключ меню → путь. Только данные для проверки прямых адресов. */
const PATHS = {
  dashboard: { queue: "/dashboard/queue", projects: "/dashboard/projects", summary: "/dashboard/summary" },
  crm: { messages: "/crm/messages", leads: "/crm/leads", clients: "/crm/clients", requests: "/crm/requests", channels: "/crm/channels", kb: "/crm/kb" },
  eds: { documents: "/eds/documents", inbox: "/eds/inbox", outbox: "/eds/outbox", projects: "/eds/projects", drafts: "/eds/drafts", approvals: "/eds/approvals", payments: "/eds/payments" },
  erp: { requests: "/erp/requests", calc: "/erp/calc", stock: "/erp/stock", catalog: "/erp/catalog", docs: "/erp/docs" },
  chats: { all: "/chats", internal: "/chats?scope=internal", external: "/chats?scope=external", contacts: "/chats/contacts" },
  admin: { roles: "/admin/roles", org: "/admin/org", integrations: "/admin/integrations", tickets: "/admin/tickets", company: "/admin/company" },
};

/** Объединённый доступ ролей: максимум по разделу. */
export function union(accessMaps) {
  const out = {};
  for (const a of accessMaps) for (const [k, v] of Object.entries(a)) if (!out[k] || RANK[v] > RANK[out[k]]) out[k] = v;
  return out;
}
export function modulesFor(access) {
  return MODULE_ORDER.filter((m) => catalog.resources.some((r) => r.module === m && access[r.key])).map((m) => MODULE_TITLES[m]);
}
/** Пункты подменю модуля (названия) по `menu` каталога: виден, если есть хотя бы один из разделов. */
export function sectionsFor(access, moduleCode) {
  const menu = catalog.menu[moduleCode] ?? {};
  return Object.entries(menu).filter(([, any]) => any.some((k) => access[k])).map(([key]) => ({ key, title: labels[moduleCode].sections[key], path: PATHS[moduleCode][key] }));
}
export function routesFor(access) {
  const visible = [];
  const hidden = [];
  for (const code of MODULE_ORDER) {
    const menu = catalog.menu[code] ?? {};
    for (const [key, any] of Object.entries(menu)) {
      const p = PATHS[code]?.[key];
      if (!p) continue;
      (any.some((k) => access[k]) ? visible : hidden).push(p);
    }
  }
  return { visible, hidden };
}
/** Ожидаемые права CRM (casbin) из `backend.crm` разделов: full включает read. */
export function crmPerms(access) {
  const out = new Set();
  for (const [key, level] of Object.entries(access)) {
    const crm = resByKey[key]?.backend?.crm;
    if (!crm) continue;
    const list = level === "full" ? [...(crm.read ?? []), ...(crm.full ?? [])] : crm.read ?? [];
    list.forEach((p) => out.add(p));
  }
  return out;
}
/** Ожидаемые права ERP: `backend.erp` разделов + `restricted_fields.*.backend.erp` видимых полей. */
export function erpPerms(access, fields = []) {
  const out = new Set();
  for (const [key, level] of Object.entries(access)) {
    const erp = resByKey[key]?.backend?.erp;
    if (!erp) continue;
    const list = level === "full" ? [...(erp.read ?? []), ...(erp.full ?? [])] : erp.read ?? [];
    list.forEach((p) => out.add(p));
  }
  for (const f of fields) (catalog.restricted_fields[f]?.backend?.erp ?? []).forEach((p) => out.add(p));
  return out;
}
export const sorted = (s) => [...s].sort();
export const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// --- результаты ----------------------------------------------------------------------------------------------------
export class Report {
  constructor(id) {
    this.id = id;
    this.rows = [];
    this.screens = [];
  }
  check(desc, ok, detail = "") {
    this.rows.push({ desc, ok: !!ok, detail: String(detail) });
    console.log(`${ok ? "PASS" : "FAIL"} [${this.id}] ${desc}${detail ? " :: " + String(detail).slice(0, 600) : ""}`);
    return ok;
  }
  note(desc, detail = "") {
    this.rows.push({ desc, ok: null, detail: String(detail) });
    console.log(`NOTE [${this.id}] ${desc}${detail ? " :: " + String(detail).slice(0, 600) : ""}`);
  }
  save() {
    writeFileSync(resolve(OUT, `result-${this.id}.json`), JSON.stringify({ rows: this.rows, screens: this.screens }, null, 2));
  }
}

// --- браузер -------------------------------------------------------------------------------------------------------
export async function launch() {
  return chromium.launch();
}
export async function newPage(browser, width = 1440) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, locale: "ru-RU", reducedMotion: "reduce", baseURL: BASE });
  const page = await ctx.newPage();
  page.consoleErrors = [];
  page.on("console", (m) => {
    if (m.type() === "error") page.consoleErrors.push(m.text().slice(0, 200));
  });
  return { ctx, page };
}

/** Лимит входа BFF — 10 в минуту на IP: скрипт держит не больше 8 входов в скользящую минуту (журнал — в QA_OUT). */
async function throttleLogin() {
  const file = resolve(OUT, "logins.json");
  for (;;) {
    let stamps = [];
    try {
      stamps = JSON.parse(readFileSync(file, "utf8"));
    } catch {
      /* первый запуск */
    }
    const now = Date.now();
    stamps = stamps.filter((t) => now - t < 61000);
    if (stamps.length < 8) {
      writeFileSync(file, JSON.stringify([...stamps, now]));
      return;
    }
    await new Promise((r) => setTimeout(r, 61000 - (now - stamps[0]) + 200));
  }
}
export async function login(page, email, password) {
  await throttleLogin();
  await page.goto("/login");
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль").fill(password);
  await page.getByRole("button", { name: "Войти" }).click();
}
/**
 * Вход и ожидание любого экрана приложения (у ролей без Dashboard первая страница — первый раздел роли). Если BFF ответил
 * 503 (CRM не уложилась в таймаут при загруженной машине), вход повторяется до 3 раз; каждый сбой печатается как FLAKY
 * и попадает в итог прогона (`loginFlakes`).
 */
export const loginFlakes = [];
export async function loginOk(page, email, password) {
  for (let attempt = 1; ; attempt++) {
    await login(page, email, password);
    try {
      await page.waitForURL((u) => !/\/(login|change-password)/.test(u.pathname), { timeout: 15000 });
      break;
    } catch (e) {
      const text = await page.getByRole("alert").first().innerText().catch(() => "");
      loginFlakes.push(`${email}: попытка ${attempt}: ${text.replace(/\n+/g, " ").slice(0, 120) || "без сообщения"}`);
      console.log(`FLAKY вход ${email}, попытка ${attempt}: ${text.slice(0, 120)}`);
      if (attempt >= 3) throw e;
    }
  }
  await page.getByRole("heading", { level: 1 }).first().waitFor();
}
export async function openAvatarMenu(page) {
  await page.getByRole("button", { name: /профиль и настройки/i }).click();
}
export async function signOut(page) {
  await openAvatarMenu(page);
  await page.getByRole("menuitem", { name: "Выйти" }).click();
  await page.waitForURL(/\/login/);
}
export async function railTexts(page) {
  const links = page.getByRole("navigation", { name: "Модули" }).getByRole("link").filter({ hasNotText: /^RT$/ });
  return (await links.allInnerTexts()).map((s) => s.trim());
}
export async function subTexts(page) {
  const nav = page.getByRole("navigation", { name: "Разделы модуля" });
  if ((await nav.count()) === 0) return [];
  return (await nav.getByRole("link").allInnerTexts()).map((s) => s.replace(/\s+\d+$/, "").trim());
}
export async function motionEnd(page) {
  await page
    .waitForFunction(
      () => !document.querySelector('[class*="-appear"], [class*="-enter"], [class*="-leave"]') && document.getAnimations().every((a) => a.playState !== "running"),
      null,
      { timeout: 5000 },
    )
    .catch(() => {});
}
export async function spaGoto(page, path) {
  await page.evaluate((p) => {
    window.history.pushState({}, "", p);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, path);
}
export async function forbidden(page, path) {
  await spaGoto(page, path);
  await page.waitForTimeout(450);
  return (await page.getByRole("heading", { level: 1, name: "Нет доступа" }).count()) === 1;
}
export async function csrf(ctx) {
  return (await ctx.cookies()).find((c) => c.name === "rt_pf_csrf")?.value ?? "";
}
/** Запрос к BFF от имени вошедшего сотрудника (cookie + CSRF). */
export async function bff(page, method, path, data) {
  const token = await csrf(page.context());
  const res = await page.request.fetch(`/api/v1${path}`, {
    method,
    headers: { "x-csrf-token": token, "content-type": "application/json" },
    ...(data === undefined ? {} : { data }),
  });
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* пусто */
  }
  return { status: res.status(), body };
}

/**
 * Проверка экрана: нет горизонтальной прокрутки, axe (wcag2a/aa/21a/21aa) без нарушений; скриншот сохраняется только для
 * ширин из `save` (по умолчанию 1440; 390 — для ключевых), остальные ширины только измеряются.
 * Имя файла — `docs/screens/r3-roles/<сценарий>-<экран>-<ширина>.png`.
 */
export async function screen(page, report, name, { widths = [1440, 1280], save = [1440], fullPage = false } = {}) {
  for (const w of widths) {
    await page.setViewportSize({ width: w, height: w === 390 ? 844 : 900 });
    await page.waitForTimeout(350);
    await motionEnd(page);
    const o = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth, bw: document.body.scrollWidth }));
    const noScroll = o.sw <= o.iw && o.bw <= o.iw;
    let violations = [];
    try {
      const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      violations = res.violations.map((v) => `${v.id}[${v.impact}]: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
    } catch (e) {
      violations = [`axe error: ${String(e).slice(0, 120)}`];
    }
    const file = `${report.id}-${name}-${w}.png`;
    if (save.includes(w)) await page.screenshot({ path: resolve(SHOTS, file), fullPage });
    report.screens.push({ name, width: w, file: save.includes(w) ? file : null, noHScroll: noScroll, scrollWidth: o.sw, axe: violations });
    report.check(`${name} @${w}: без горизонтальной прокрутки`, noScroll, `scrollWidth=${o.sw}, innerWidth=${o.iw}`);
    report.check(`${name} @${w}: axe без нарушений`, violations.length === 0, violations.join(" ;; "));
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(250);
}

// --- CRM API (вне браузера: права, пароли, роли) -------------------------------------------------------------------
export async function crm(method, path, token, body) {
  const res = await fetch(CRM + path, {
    method,
    headers: { "content-type": "application/json", ...(token ? { authorization: "Bearer " + token } : {}) },
    ...(body == null ? {} : { body: JSON.stringify(body) }),
  });
  const text = await res.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    /* не JSON */
  }
  return { status: res.status, body: json ?? text };
}
export async function crmLogin(email, password) {
  const r = await crm("POST", "/api/v1/auth/login", null, { email, password });
  if (r.status !== 200) throw new Error(`CRM login ${email}: ${r.status} ${JSON.stringify(r.body).slice(0, 200)}`);
  return r.body.access_token;
}
export function flattenPerms(matrix) {
  const out = new Set();
  for (const [res, acts] of Object.entries(matrix)) for (const [a, v] of Object.entries(acts)) if (v) out.add(`${res}:${a}`);
  return out;
}
