import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";
import { LAPTOP_WIDTHS, expectFitsFrame } from "./support/layout";

// Polish pw1 · раскладка через общие компоненты: таблицы в рамке на 1512 и 1280 (боковое окно закрыто и открыто),
// одна строка вкладок и фильтров, заголовок без пересказа, «Только просмотр» один раз.
// Снимки 1512, 1280, 390 и axe — `E2E_SCREENSHOT_DIR=docs/screens/pw1-layout`.

const REGISTRIES = [
  { name: "catalog", path: "/erp/catalog" },
  { name: "catalog-waiting", path: "/erp/catalog?review=waiting" },
  { name: "org", path: "/admin/org?view=list" },
  { name: "zones", path: "/admin/zones" },
  { name: "people", path: "/chats/contacts" },
  { name: "inbox", path: "/eds/inbox?status=all" },
  { name: "documents", path: "/eds/documents?scope=all" },
  { name: "approvals", path: "/eds/approvals" },
  { name: "drafts", path: "/eds/drafts?scope=all" },
  { name: "projects", path: "/eds/projects" },
  { name: "payments", path: "/eds/payments" },
  { name: "requests", path: "/erp/requests" },
  { name: "leads", path: "/crm/leads" },
  { name: "clients", path: "/crm/clients" },
  { name: "stock", path: "/erp/stock" },
  { name: "stock-orders", path: "/erp/stock?view=orders" },
  { name: "stock-receipts", path: "/erp/stock?view=receipts" },
] as const;

async function expectNoViolations(page: Page, context: string): Promise<void> {
  await waitForMotionEnd(page);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`),
    context,
  ).toEqual([]);
}

/** Реестры с боковым окном строки: открывается щелчком по названию первой строки. */
const WITH_PANEL = [
  { name: "catalog", path: "/erp/catalog", open: /^Открыть позицию/ },
  { name: "org", path: "/admin/org?view=list", open: /^Открыть карточку/ },
  { name: "zones", path: "/admin/zones", open: /^Открыть зону/ },
] as const;

test.describe("Polish pw1 · раскладка", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("реестры помещаются в рамку на 1512 и 1280", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    for (const screen of REGISTRIES) {
      await spaGoto(page, screen.path);
      await expect(page.locator("main h1").first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      await expectFitsFrame(page, screen.name);
    }
  });

  test("с открытым боковым окном таблица остаётся в рамке", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    for (const screen of WITH_PANEL) {
      await spaGoto(page, screen.path);
      await page.waitForLoadState("networkidle");
      await page.locator("main table").getByLabel(screen.open).first().click();
      await page.waitForTimeout(400);
      await expectFitsFrame(page, `${screen.name} + panel`);
    }
  });

  test("шкала проекта: подписи видны и не обрезаны на 1512 и 1280, в том числе с окном справа", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/eds/projects/%D0%9F%D0%A0-2026-104");
    await expect(page.getByRole("list", { name: /^Путь/ })).toBeVisible();
    for (const open of [false, true]) {
      if (open) {
        const show = page.getByRole("button", { name: "Показать панель", exact: true });
        if ((await show.count()) > 0) await show.click();
        await expect(page.locator("#pf-context-panel")).toBeVisible();
      }
      for (const width of LAPTOP_WIDTHS) {
        await page.setViewportSize({ width, height: 982 });
        await page.waitForTimeout(150);
        const bad = await page.evaluate<
          string[]
        >(`(() => [...document.querySelectorAll(".pf-step-label")]
          .filter((el) => {
            const box = el.getBoundingClientRect();
            const hidden = box.width <= 1 || box.height <= 1;
            return hidden || el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1;
          })
          .map((el) => el.textContent.trim())
        )()`);
        expect(bad, `шкала ${String(width)} окно ${String(open)}`).toEqual([]);
      }
    }
  });

  test("вкладки раздела стоят под заголовком, одна строка вкладок и одна строка фильтров", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    for (const path of ["/erp/catalog", "/erp/stock", "/erp/docs"]) {
      await spaGoto(page, path);
      const heading = page.locator("main h1").first();
      await expect(heading).toBeVisible();
      const tabs = page.locator("nav.pf-shell-tabs");
      await expect(tabs).toHaveCount(1);
      const [h, t] = await Promise.all([heading.boundingBox(), tabs.boundingBox()]);
      expect(t?.y ?? 0, `${path}: вкладки раздела под заголовком`).toBeGreaterThan(h?.y ?? 0);
    }
    // лиды и документы: вкладки над строкой фильтров, а не между фильтрами и списком
    for (const path of ["/crm/leads", "/eds/documents?scope=all"]) {
      await spaGoto(page, path);
      // spaGoto не ждёт смены экрана: без ожидания адреса и раскладки боксы брались у прошлого экрана посреди перехода
      await expect(page).toHaveURL(new RegExp(path.split("?")[0].replace(/\//g, "\\/")));
      await expect(page.locator("main .pf-filter-bar").first()).toBeVisible();
      await expect(page.locator("main table").first()).toBeVisible();
      await expect(page.locator("main .ant-tabs-nav").first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      await expect
        .poll(
          async () => {
            const [tabs, filters, table] = await Promise.all([
              page.locator("main .ant-tabs-nav").first().boundingBox(),
              page.locator("main .pf-filter-bar").first().boundingBox(),
              page.locator("main table").first().boundingBox(),
            ]);
            const order: string[] = [];
            if ((tabs?.y ?? 0) >= (filters?.y ?? 0)) order.push("вкладки выше фильтров");
            if ((filters?.y ?? 0) >= (table?.y ?? 0)) order.push("фильтры выше списка");
            return order;
          },
          { message: `${path}: порядок вкладок, фильтров и списка`, timeout: 10_000 },
        )
        .toEqual([]);
      expect(await page.locator("main .ant-tabs-nav").count(), `${path}: одна строка вкладок`).toBe(
        1,
      );
    }
  });

  test("«Только просмотр» один раз и без пересказа под заголовком", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    for (const path of ["/admin/org?view=list", "/admin/zones", "/admin/integrations"]) {
      await spaGoto(page, path);
      await expect(page.locator("main h1").first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      const text = await page.locator("main").innerText();
      const count = (text.match(/Только просмотр/g) ?? []).length;
      expect(count, `${path}: «Только просмотр» не больше одного раза`).toBeLessThanOrEqual(1);
    }
  });

  test("«Только просмотр» в базе знаний: ровно один раз", async ({ page }) => {
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/crm/kb");
    await expect(page.getByRole("heading", { level: 1, name: "База знаний" })).toBeVisible();
    await page.waitForLoadState("networkidle");
    const text = await page.locator("body").innerText();
    expect((text.match(/Только просмотр/g) ?? []).length).toBe(1);
  });

  test("«Только просмотр» один раз и при открытой карточке сотрудника", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/admin/org?view=list");
    await expect(page.locator("main h1").first()).toBeVisible();
    await page
      .locator("main table")
      .getByLabel(/^Открыть карточку/)
      .first()
      .click();
    await page.waitForLoadState("networkidle");
    const text = await page.locator("body").innerText();
    expect((text.match(/Только просмотр/g) ?? []).length).toBeLessThanOrEqual(1);
  });

  test("каталог: одна строка вкладок раздела и одна строка фильтров на 1512 и 1280", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/erp/catalog");
    await expect(page.locator("main .pf-filter-bar").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    for (const width of LAPTOP_WIDTHS) {
      await page.setViewportSize({ width, height: 982 });
      await page.waitForTimeout(150);
      // одна строка: высота строки фильтров не больше самого высокого её элемента
      const lines = await page.evaluate<number>(`(() => {
        const bar = document.querySelector("main .pf-filter-bar");
        let tallest = 0;
        for (const el of bar.children) tallest = Math.max(tallest, el.getBoundingClientRect().height);
        return Math.round(bar.getBoundingClientRect().height / Math.max(tallest, 1));
      })()`);
      expect(lines, `catalog · ${String(width)}: фильтры в одну строку`).toBe(1);
    }
  });

  test("снимки 1512, 1280 и 390 и axe", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    for (const screen of [
      { name: "catalog", path: "/erp/catalog" },
      { name: "org", path: "/admin/org?view=list" },
      { name: "zones", path: "/admin/zones" },
      { name: "leads", path: "/crm/leads" },
      { name: "documents", path: "/eds/documents?scope=all" },
      { name: "stock", path: "/erp/stock" },
      { name: "people", path: "/chats/contacts" },
      { name: "project-card", path: "/eds/projects/%D0%9F%D0%A0-2026-104" },
    ]) {
      await spaGoto(page, screen.path);
      await expect(page.locator("main h1").first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      for (const width of [1512, 1280, 390] as const) {
        await page.setViewportSize({ width, height: width === 390 ? 844 : 982 });
        await expectNoViolations(page, `${screen.name} ${String(width)}`);
        await settledScreenshot(page, screen.name);
      }
      await page.setViewportSize({ width: 1440, height: 900 });
    }
  });
});
