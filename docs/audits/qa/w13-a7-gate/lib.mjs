// W13-A7: общие помощники сценариев гейта C2a против живого стенда `rt-c2` (Caddy -> BFF Платформы -> CRM/ERP/EDS), не MSW.
// Playwright, axe и yaml берутся из зависимостей `apps/platform/web` (ничего не ставим). Не входит в `make check-platform`.
// Пароли и коды: пароль администратора и сотрудников генерируются на лету и лежат ТОЛЬКО в файле состояния вне репозитория
// (QA_STATE); на снимках поля с кодом/паролем закрываются маской (`shot(..., {mask})`), в отчёт они не попадают.
import { createRequire } from "node:module";
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
export const ROOT = resolve(here, "../../../..");
const req = createRequire(resolve(ROOT, "apps/platform/web/package.json"));
export const { chromium } = req("@playwright/test");
export const AxeBuilder = req("@axe-core/playwright").default ?? req("@axe-core/playwright");

export const BASE = process.env.QA_BASE ?? "http://platform.localhost:8097";
export const SHOTS = process.env.QA_SHOTS ?? resolve(ROOT, "docs/screens/w13-a7-gate");
export const OUT = process.env.QA_OUT ?? "/tmp/qa-w13-a7-out";
export const STATE_FILE = process.env.QA_STATE ?? resolve(OUT, "state.json");
mkdirSync(SHOTS, { recursive: true });
mkdirSync(OUT, { recursive: true });

export const secret = (prefix) => `${prefix}-${randomBytes(6).toString("hex")}-Aa1`;

export function state() {
  return existsSync(STATE_FILE) ? JSON.parse(readFileSync(STATE_FILE, "utf8")) : {};
}
export function saveState(patch) {
  writeFileSync(STATE_FILE, JSON.stringify({ ...state(), ...patch }, null, 1), { mode: 0o600 });
}

export class Report {
  constructor(id) {
    this.id = id;
    this.rows = [];
    this.screens = [];
  }
  check(desc, ok, detail = "") {
    this.rows.push({ desc, ok: !!ok, detail: String(detail) });
    console.log(`${ok ? "PASS" : "FAIL"} [${this.id}] ${desc}${detail ? " :: " + detail : ""}`);
    return ok;
  }
  note(desc, detail = "") {
    this.rows.push({ desc, ok: null, detail: String(detail) });
    console.log(`NOTE [${this.id}] ${desc}${detail ? " :: " + detail : ""}`);
  }
  save() {
    writeFileSync(resolve(OUT, `result-${this.id}.json`), JSON.stringify({ rows: this.rows, screens: this.screens }, null, 2));
  }
}

export async function launch() {
  return chromium.launch();
}
export async function newPage(browser, width = 1440, opts = {}) {
  const ctx = await browser.newContext({
    viewport: { width, height: width === 390 ? 844 : 900 },
    locale: "ru-RU",
    // как у пользователя с «уменьшить движение»: antd без анимаций, axe не ловит полупрозрачные оверлеи посреди перехода
    reducedMotion: "reduce",
    baseURL: BASE,
    acceptDownloads: true,
    ...opts,
  });
  const page = await ctx.newPage();
  page.consoleErrors = [];
  page.failed = [];
  page.on("console", (m) => {
    if (m.type() === "error") page.consoleErrors.push(m.text().slice(0, 240));
  });
  page.on("response", (r) => {
    if (r.status() >= 500) page.failed.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`);
  });
  return { ctx, page };
}

/** Лимит входа BFF — 10 в минуту на IP: не больше 8 входов в скользящую минуту (журнал времён — в OUT). */
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
export async function loginOk(page, email, password) {
  await login(page, email, password);
  await page.waitForURL(/\/(dashboard\/queue|admin\/setup)/, { timeout: 20000 });
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
export async function motionEnd(page) {
  await page
    .waitForFunction(
      () =>
        !document.querySelector('[class*="-appear"], [class*="-enter"], [class*="-leave"]') &&
        document.getAnimations().every((a) => a.playState !== "running"),
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
  await page.waitForTimeout(400);
}
export async function toastsGone(page) {
  await page.locator(".ant-message-notice").first().waitFor({ state: "detached", timeout: 8000 }).catch(() => {});
}

/** Снимок с масками (поля с кодом/паролем закрываются). Имя: <id>-<name>-<ширина>.png */
export async function shot(page, report, name, { mask = [], full = false } = {}) {
  await page.waitForTimeout(350);
  await motionEnd(page);
  const w = page.viewportSize()?.width ?? 0;
  const file = `${report.id}-${name}-${w}.png`;
  await page.screenshot({ path: resolve(SHOTS, file), mask, maskColor: "#6b7280", fullPage: full });
  report.screens.push({ name, width: w, file });
  return file;
}

/**
 * Проверка экрана на 1440 (и 390, если narrow): нет горизонтальной прокрутки, axe (wcag2a/aa/21a/21aa), снимок.
 * Состояние страницы (открытая панель, форма) сохраняется. `mask` — локаторы, закрываемые на снимке.
 */
export async function screen(page, report, name, { narrow = true, mask = [], exclude = [] } = {}) {
  const list = narrow ? [1440, 390] : [1440];
  for (const w of list) {
    await page.setViewportSize({ width: w, height: w === 390 ? 844 : 900 });
    await page.waitForTimeout(400);
    await motionEnd(page);
    const o = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth, bw: document.body.scrollWidth }));
    const noScroll = o.sw <= o.iw && o.bw <= o.iw;
    let violations = [];
    try {
      let b = new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]);
      for (const sel of exclude) b = b.exclude(sel);
      const res = await b.analyze();
      violations = res.violations.map((v) => `${v.id}[${v.impact}]: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
    } catch (e) {
      violations = [`axe error: ${String(e).slice(0, 120)}`];
    }
    const file = `${report.id}-${name}-${w}.png`;
    await page.screenshot({ path: resolve(SHOTS, file), mask, maskColor: "#6b7280" });
    report.screens.push({ name, width: w, file, noHScroll: noScroll, axe: violations });
    report.check(`${name} @${w}: без горизонтальной прокрутки`, noScroll, `scrollWidth=${o.sw}, innerWidth=${o.iw}`);
    report.check(`${name} @${w}: axe без нарушений`, violations.length === 0, violations.join(" ;; "));
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(250);
}

/** Вызов BFF из страницы (с её cookie и CSRF) — для проверок прав и ответов без экрана. */
export async function bff(page, method, path, body) {
  return page.evaluate(
    async ([m, p, b]) => {
      const csrf = /rt_pf_csrf=([^;]+)/.exec(document.cookie)?.[1] ?? "";
      const r = await fetch(p, {
        method: m,
        headers: { "Content-Type": "application/json", "X-CSRF-Token": decodeURIComponent(csrf) },
        body: b === undefined ? undefined : JSON.stringify(b),
      });
      let j = null;
      try {
        j = await r.json();
      } catch {
        /* не JSON */
      }
      return { status: r.status, body: j };
    },
    [method, path, body],
  );
}
