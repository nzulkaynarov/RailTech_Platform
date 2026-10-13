// UI-ревью запущенного стенда: вход под ролью, скриншот каждого маршрута на десктопе и телефоне,
// axe-core (WCAG 2.1 A/AA), горизонтальная прокрутка, заголовок вкладки, ошибки консоли и 4xx/5xx.
// Без аргументов — подсказка. Вывод: review-out/<viewport>-<role>-<route>.png и review-out/summary.json.
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { chromium } from "@playwright/test";

const HELP = `UI-ревью стенда (скилл ui-review)

  REVIEW_EMAIL=… REVIEW_PASSWORD=… node scripts/ui-review.mjs <role> <desktop|mobile> <route> [route…]

  role      — метка для имён файлов (admin / manager / viewer)
  route     — путь с ведущим «/», например /inbox "/settings?section=texts"
  BASE_URL  — стенд (по умолчанию http://localhost)
  REVIEW_BROWSER=chrome — использовать установленный Chrome вместо chromium Playwright

Итог — review-out/summary.json; код выхода 1, если есть нарушения axe или горизонтальная прокрутка.`;

const [role, viewportName, ...routes] = process.argv.slice(2);
if (!role || !viewportName || routes.length === 0) {
  console.log(HELP);
  process.exit(routes.length === 0 && role ? 1 : 0);
}
const email = process.env["REVIEW_EMAIL"];
const password = process.env["REVIEW_PASSWORD"];
if (!email || !password) {
  console.error("Нужны REVIEW_EMAIL и REVIEW_PASSWORD (учётка стенда, не из git).");
  process.exit(1);
}
const base = process.env["BASE_URL"] ?? "http://localhost";
const mobile = viewportName === "mobile";
const outDir = resolve("review-out");
mkdirSync(outDir, { recursive: true });

const launch = process.env["REVIEW_BROWSER"] === "chrome" ? { channel: "chrome" } : {};
const browser = await chromium.launch(launch);
const context = await browser.newContext({
  viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 },
  locale: "ru-RU",
  isMobile: mobile,
  hasTouch: mobile,
});
const page = await context.newPage();
const problems = new Set();
page.on("console", (m) => {
  if (m.type() === "error" && !m.text().startsWith("Warning:"))
    problems.add(`console: ${m.text().slice(0, 160)}`);
});
page.on("response", (r) => {
  const url = new URL(r.url());
  if (r.status() >= 400 && url.pathname !== "/api/v1/auth/refresh") {
    problems.add(`${String(r.status())} ${url.pathname}`);
  }
});

await page.goto(`${base}/login`);
await page.getByLabel("Email").fill(email);
await page.getByLabel("Пароль").fill(password);
await page.getByRole("button", { name: "Войти" }).click();
await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 15_000 });

const results = [];
for (const route of routes) {
  await page.goto(`${base}${route}`);
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => undefined);
  await page.waitForTimeout(500);
  const slug = route.replace(/[/?=&]+/g, "_").replace(/^_/, "") || "root";
  const file = `${outDir}/${viewportName}-${role}-${slug}.png`;
  await page.screenshot({ path: file, fullPage: true });
  const axe = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const violations = axe.violations.map(
    (v) =>
      `${v.id} [${v.impact ?? "?"}] ×${String(v.nodes.length)}: ${v.nodes
        .slice(0, 2)
        .map((n) => n.target.join(" "))
        .join(" | ")}`,
  );
  const hscroll = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  results.push({ route, title: await page.title(), hscroll, violations, file });
}
await browser.close();

const summary = { base, role, viewport: viewportName, results, problems: [...problems] };
writeFileSync(`${outDir}/summary.json`, JSON.stringify(summary, null, 1));
for (const r of results) {
  const flags = [
    r.hscroll ? "HSCROLL" : "",
    r.violations.length ? `axe ${String(r.violations.length)}` : "",
  ]
    .filter(Boolean)
    .join(", ");
  console.log(`${r.route}  «${r.title}»  ${flags || "ok"}`);
  for (const v of r.violations) console.log(`   ${v}`);
}
if (summary.problems.length)
  console.log(`Ошибки консоли/сети:\n   ${summary.problems.join("\n   ")}`);
const failed = results.some((r) => r.hscroll || r.violations.length);
process.exit(failed ? 1 : 0);
