// QA-P1: общие помощники сценариев против живого стенда (не MSW). Не входит в `make check-platform` и не трогает e2e Платформы.
// Playwright, axe и yaml берутся из зависимостей `apps/platform/web` (node_modules рядом с кодом web, ничего не ставим).
import { createRequire } from "node:module";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
export const ROOT = resolve(here, "../../../..");
const req = createRequire(resolve(ROOT, "apps/platform/web/package.json"));
export const { chromium } = req("@playwright/test");
export const AxeBuilder = req("@axe-core/playwright").default ?? req("@axe-core/playwright");
const yaml = req("yaml");

export const BASE = process.env.QA_BASE ?? "http://platform.localhost:18089";
export const SHOTS = process.env.QA_SHOTS ?? resolve(ROOT, "docs/screens/plt-p1");
export const OUT = process.env.QA_OUT ?? "/tmp/qa-p1-out";
mkdirSync(SHOTS, { recursive: true });
mkdirSync(OUT, { recursive: true });

/** Учётные данные стенда: файл KEY=VALUE вне репозитория (QA_CREDS). Пароли в отчёт и скриншоты не попадают. */
export function creds() {
  const file = process.env.QA_CREDS;
  if (!file) throw new Error("QA_CREDS не задан: файл KEY=VALUE вне репозитория");
  return Object.fromEntries(
    readFileSync(file, "utf8")
      .trim()
      .split("\n")
      .map((l) => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1)]),
  );
}

// --- матрица ролей из контракта (ожидания строятся из неё, а не из кода web) ---------------------------------------
const matrix = yaml.parse(readFileSync(resolve(ROOT, "packages/contracts/platform-rbac.yaml"), "utf8"));
const MODULE_ORDER = ["dashboard", "crm", "eds", "erp", "chats", "admin"];
export const MODULE_TITLES = { dashboard: "Dashboard", crm: "CRM", eds: "EDS", erp: "ERP", chats: "Chats", admin: "Admin" };
const RANK = { hidden: 0, read: 1, full: 2 };

export function levelOf(resource, roles) {
  return roles.map((r) => resource.access[r]).reduce((a, b) => (RANK[b] > RANK[a] ? b : a), "hidden");
}
export function modulesFor(roles) {
  return MODULE_ORDER.filter((m) =>
    matrix.resources.some((r) => r.module === m && levelOf(r, roles) !== "hidden"),
  ).map((m) => MODULE_TITLES[m]);
}
const ROUTE_OF = {
  "dashboard.summary": "/dashboard/summary",
  "crm.leads": "/crm/leads",
  "crm.clients": "/crm/clients",
  "eds.inbox": "/eds/inbox",
  "eds.drafts": "/eds/drafts",
  "eds.projects": "/eds/projects",
  "eds.payments": "/eds/payments",
  "erp.calc": "/erp/calc",
  "erp.stock": "/erp/stock",
  "chats.external": "/chats?scope=external",
  admin: "/admin/roles",
};
export function routesFor(roles) {
  const hidden = [];
  const visible = [];
  for (const r of matrix.resources) {
    const route = ROUTE_OF[r.key];
    if (!route) continue;
    (levelOf(r, roles) === "hidden" ? hidden : visible).push(route);
  }
  return { hidden, visible };
}

// --- результаты ---------------------------------------------------------------------------------------------------
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

// --- браузер ------------------------------------------------------------------------------------------------------
export async function launch() {
  return chromium.launch();
}
export async function newPage(browser, width = 1440) {
  const ctx = await browser.newContext({
    viewport: { width, height: 900 },
    locale: "ru-RU",
    // как у пользователя с «уменьшить движение»: antd без анимаций, axe не ловит полупрозрачные оверлеи посреди перехода
    reducedMotion: "reduce",
    baseURL: BASE,
  });
  const page = await ctx.newPage();
  page.consoleErrors = [];
  page.on("console", (m) => {
    if (m.type() === "error") page.consoleErrors.push(m.text().slice(0, 200));
  });
  return { ctx, page };
}

/**
 * Лимит входа BFF — 10 в минуту на IP (все запросы стенда идут с одного адреса), поэтому скрипт сам не даёт больше 8 входов
 * в скользящую минуту (журнал времён — в QA_OUT, общий для запусков).
 */
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
  await page.waitForURL(/\/dashboard\/queue/, { timeout: 15000 });
  await page.getByRole("heading", { level: 1 }).waitFor();
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
  await page.evaluate(
    (p) => {
      window.history.pushState({}, "", p);
      window.dispatchEvent(new PopStateEvent("popstate"));
    },
    path,
  );
}

/**
 * Проверка экрана на 1440 / 1280 (и 390, если narrow): нет горизонтальной прокрутки страницы, axe (wcag2a/aa/21a/21aa) без
 * нарушений, скриншот `docs/screens/plt-p1/<id>-<name>-<ширина>.png`. Состояние страницы (открытый поповер, карточка) сохраняется.
 */
export async function screen(page, report, name, { narrow = false, widths } = {}) {
  const list = widths ?? (narrow ? [1440, 1280, 390] : [1440, 1280]);
  for (const w of list) {
    await page.setViewportSize({ width: w, height: w === 390 ? 844 : 900 });
    await page.waitForTimeout(350);
    await motionEnd(page);
    const overflow = await page.evaluate(() => ({
      sw: document.documentElement.scrollWidth,
      iw: window.innerWidth,
      bw: document.body.scrollWidth,
    }));
    const noScroll = overflow.sw <= overflow.iw && overflow.bw <= overflow.iw;
    let violations = [];
    try {
      const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      violations = res.violations.map((v) => `${v.id}[${v.impact}]: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
    } catch (e) {
      violations = [`axe error: ${String(e).slice(0, 120)}`];
    }
    const file = `${report.id}-${name}-${w}.png`;
    await page.screenshot({ path: resolve(SHOTS, file) });
    report.screens.push({ name, width: w, file, noHScroll: noScroll, scrollWidth: overflow.sw, axe: violations });
    report.check(`${name} @${w}: без горизонтальной прокрутки`, noScroll, `scrollWidth=${overflow.sw}, innerWidth=${overflow.iw}`);
    report.check(`${name} @${w}: axe без нарушений`, violations.length === 0, violations.join(" ;; "));
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(250);
}
