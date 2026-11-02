// D2-6: общие помощники гейта D2 против живого стенда `rt-gate-d26` (Caddy -> BFF Платформы -> CRM/ERP/EDS). Надстройка над помощниками гейта C2a.
// Запуск из корня worktree: QA_BASE=http://platform.localhost:8101 QA_OUT=<каталог вне репозитория> QA_COMPOSE="<docker compose ... -p rt-gate-d26>" node docs/audits/qa/d26-gate/run.mjs <сценарии>
import { execSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

process.env.QA_SHOTS ??= resolve(dirname(fileURLToPath(import.meta.url)), "../../../screens/w17-d2-6");
export const lib = await import("../w13-a7-gate/lib.mjs");
export const { Report, launch, newPage, openAvatarMenu, spaGoto, screen, shot, toastsGone, bff, state, saveState, secret, motionEnd } = lib;

export const compose = (args) => {
  const c = process.env.QA_COMPOSE;
  if (!c) throw new Error("QA_COMPOSE не задан");
  return execSync(`${c} ${args}`, { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
};
export const PANEL = "#pf-context-panel";
export const ADMIN = "admin.d26@demo.example";
export const PEOPLE = {
  registrar: { email: "registrar.d26@demo.example", name: "Демо Регистраторова", tpl: "Делопроизводитель" },
  director: { email: "director.d26@demo.example", name: "Демо Директорова", tpl: "Директор" },
  manager_all: { email: "universal.d26@demo.example", name: "Демо Универсалов", tpl: "Менеджер-универсал" },
  accountant: { email: "accountant.d26@demo.example", name: "Демо Бухгалтерова", tpl: "Бухгалтер" },
  supply: { email: "supply.d26@demo.example", name: "Демо Снабженцева", tpl: "Снабженец" },
  engineer: { email: "engineer.d26@demo.example", name: "Демо Инженерова", tpl: "Гл. инженер" },
};

export async function np(browser, ...rest) {
  const res = await newPage(browser, ...rest);
  res.page.setDefaultNavigationTimeout(60000);
  res.page.setDefaultTimeout(30000);
  return res;
}

export async function step(page, r, desc, fn, { noShot = false } = {}) {
  try {
    await fn();
    return r.check(desc, true);
  } catch (e) {
    const msg = String(e.message ?? e).split("\n").slice(0, 3).join(" / ").slice(0, 400);
    r.check(desc, false, msg);
    const mask = [page.locator('input[type="password"]'), page.getByLabel("Временный пароль", { exact: true })];
    if (!noShot) await shot(page, r, `FAIL-${r.rows.length}`, { mask }).catch(() => {});
    return false;
  }
}

export const pwOf = (email) => state().passwords?.[email] ?? state().temps?.[email];

/** Вход: временный пароль -> свой; приветствие первого входа закрывается. */
export async function signIn(page, r, email, password) {
  await page.context().clearCookies();
  await lib.login(page, email, password);
  await page.waitForURL(/\/(dashboard\/queue|admin\/setup|change-password|crm|eds|erp|chats|admin)/, { timeout: 60000, waitUntil: "commit" });
  let pw = password;
  if (/change-password/.test(page.url())) {
    pw = secret("own");
    await page.getByLabel("Текущий пароль").fill(password);
    await page.getByLabel("Новый пароль", { exact: true }).fill(pw);
    await page.getByLabel("Повторите новый пароль").fill(pw);
    await page.getByRole("button", { name: "Сменить пароль" }).click();
    await page.waitForURL((u) => !/change-password/.test(String(u)), { timeout: 60000, waitUntil: "commit" });
    const s = state();
    saveState({ passwords: { ...(s.passwords ?? {}), [email]: pw } });
  }
  await page.getByRole("heading", { level: 1 }).first().waitFor({ timeout: 20000 });
  const welcome = page.getByRole("dialog").filter({ hasText: "Добро пожаловать" });
  if (await welcome.waitFor({ state: "visible", timeout: 4000 }).then(() => true).catch(() => false)) {
    await welcome.getByRole("button", { name: "Больше не показывать" }).click();
    await welcome.waitFor({ state: "hidden" }).catch(() => {});
  }
  return pw;
}

export async function settle(page) {
  await page.locator(".ant-skeleton").first().waitFor({ state: "detached", timeout: 20000 }).catch(() => {});
  await page.getByText(/^Загружаем/).first().waitFor({ state: "detached", timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(500);
}

/** Только текущая ширина (для открытых форм и панелей: смена ширины пересобирает панель и стирает ввод). */
export async function screenHere(page, report, name, { mask = [] } = {}) {
  await lib.motionEnd(page);
  const w = page.viewportSize()?.width ?? 0;
  const o = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth, bw: document.body.scrollWidth }));
  const noScroll = o.sw <= o.iw && o.bw <= o.iw;
  let violations = [];
  try {
    const res = await new lib.AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    violations = res.violations.map((v) => `${v.id}[${v.impact}]: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
  } catch (e) {
    violations = [`axe error: ${String(e).slice(0, 120)}`];
  }
  const file = `${report.id}-${name}-${w}.png`;
  await page.screenshot({ path: `${process.env.QA_SHOTS}/${file}`, mask, maskColor: "#6b7280" });
  report.screens.push({ name, width: w, file, noHScroll: noScroll, axe: violations });
  report.check(`${name} @${w}: без горизонтальной прокрутки`, noScroll, `scrollWidth=${o.sw}, innerWidth=${o.iw}`);
  report.check(`${name} @${w}: axe без нарушений`, violations.length === 0, violations.join(" ;; "));
}
