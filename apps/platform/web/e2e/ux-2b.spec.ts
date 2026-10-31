import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// UX-2b «Суммы, цвета статусов, телефон» на MSW: суммы в сумах — словом «сум», без «UZS» рядом; числа в таблицах — вправо;
// цвета статусов — из одной карты (`STATUS_TONE`); на 390 страница не шире экрана ни на одном основном экране, фильтр
// «Входящих» и вкладки «Склада» прокручиваются вбок внутри своей полосы, без меню «…». axe (WCAG 2.1 AA) — 0 нарушений;
// снимки — `E2E_SCREENSHOT_DIR=docs/screens/ux-2b`.

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

/** Ни страница, ни рабочая область не прокручиваются вбок: широкое — только в своей полосе прокрутки. */
async function horizontalOverflow(page: Page): Promise<{ page: number; main: number }> {
  return page.evaluate(`(() => {
    const main = document.getElementById("main-content");
    return {
      page: document.documentElement.scrollWidth - window.innerWidth,
      main: main ? main.scrollWidth - main.clientWidth : 0,
    };
  })()`);
}

const enc = encodeURIComponent;

/** Основные экраны сотрудников (учётка со всеми ролями): списки, карточки, настройки. */
const ROUTES = [
  "/dashboard/queue",
  "/dashboard/projects",
  "/crm/leads",
  "/crm/clients",
  "/crm/messages",
  "/crm/kb",
  "/eds/inbox",
  `/eds/inbox/${enc("ВХ-104/26")}`,
  "/eds/drafts",
  "/eds/approvals",
  "/eds/documents",
  "/eds/projects",
  `/eds/projects/${enc("ПР-2026-104")}`,
  "/eds/payments",
  "/eds/new",
  "/erp/calc",
  `/erp/calc/${enc("ЗВ-2026-097")}`,
  "/erp/requests",
  "/erp/stock",
  "/erp/stock?view=orders",
  "/erp/stock?view=receipts",
  "/erp/stock?view=shipments",
  "/erp/catalog",
  "/erp/docs",
  "/chats",
  "/admin/org",
  "/admin/roles",
  "/admin/company",
  "/admin/integrations",
  "/admin/bus",
  "/admin/audit",
  "/admin/bot",
  "/admin/setup",
  "/admin/articles",
  "/me",
  "/help",
] as const;

test.describe("UX-2b: суммы, статусы, телефон", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("на 390 нет горизонтальной прокрутки страницы на основных экранах", async ({ page }) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "all@demo.example");
    const wide: string[] = [];
    for (const route of ROUTES) {
      await spaGoto(page, route);
      await expect(page.getByRole("heading", { level: 1 }).first(), route).toBeVisible();
      await expect(page.locator("[data-pf-skeleton]")).toHaveCount(0);
      // экран дорисовался (ответы MSW, ленивые чанки): мерить прежний экран нельзя
      await page.waitForTimeout(400);
      const overflow = await horizontalOverflow(page);
      if (overflow.page > 0 || overflow.main > 0) {
        wide.push(
          `${route}: страница +${String(overflow.page)}, область +${String(overflow.main)}`,
        );
      }
    }
    expect(wide).toEqual([]);
  });

  for (const width of [1440, 390] as const) {
    test(`Счета и оплаты: суммы в сумах, без «UZS», числа вправо — ${String(width)}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "accountant@demo.example");
      await spaGoto(page, "/eds/payments");
      await expect(page.getByRole("heading", { level: 1, name: "Счета и оплаты" })).toBeVisible();
      const main = page.locator("#main-content");
      await expect(main.getByText(/\d\sсум/).first()).toBeVisible();
      await expect(main.getByText(/остаток [\d\s]+сум/).first()).toBeVisible();
      await expect(main).not.toContainText("UZS");
      if (width === 1440) {
        const amount = main.locator("td.pf-col-num").first();
        await expect(amount).toHaveCSS("text-align", "right");
      }
      await expectNoViolations(page, `счета ${String(width)}`);
      await settledScreenshot(page, "payments");
    });
  }

  test("Расчёт: строки с суммами — числа вправо, итог «сум» — 1440", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, `/erp/calc/${enc("ЗВ-2026-097")}`);
    await expect(page.getByRole("heading", { level: 1, name: /ЗВ-2026-097/ })).toBeVisible();
    const table = page.locator("table.pf-calc-lines");
    await expect(table).toBeVisible();
    await expect(table.locator("th.pf-col-num").first()).toHaveCSS("text-align", "right");
    await expect(table.locator("tfoot td.pf-col-num").first()).toHaveCSS("text-align", "right");
    await expect(page.locator("#main-content")).not.toContainText("UZS");
    await expectNoViolations(page, "расчёт 1440");
    await settledScreenshot(page, "calc-lines");
  });

  for (const width of [1440, 390] as const) {
    test(`Склад: остатки — числа вправо, на 390 тег в карточке и вкладки без «…» — ${String(width)}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "supply@demo.example");
      await spaGoto(page, "/erp/stock");
      await expect(page.getByRole("heading", { level: 1, name: "Склад" })).toBeVisible();
      await expect(page.getByText(/Свободно · \d+/).first()).toBeVisible();
      // меню «…» antd не показывается, все вкладки — в ленте и достижимы
      await expect(page.locator(".pf-tabs-bar .ant-tabs-nav-operations")).toBeHidden();
      for (const name of ["Остатки и резервы", "Заказы поставщикам", "Приёмка", "Отгрузки"]) {
        await expect(page.getByRole("tab", { name })).toBeAttached();
      }
      if (width === 1440) {
        await expect(page.locator("th.pf-col-num").first()).toHaveCSS("text-align", "right");
      } else {
        // тег «Свободно · N» внутри карточки
        const card = page.locator(".pf-calc-cards > li").first();
        const tag = card.locator(".ant-tag").first();
        const [cardBox, tagBox] = [await card.boundingBox(), await tag.boundingBox()];
        expect(tagBox && cardBox && tagBox.x + tagBox.width <= cardBox.x + cardBox.width).toBe(
          true,
        );
      }
      expect(await horizontalOverflow(page)).toEqual({ page: 0, main: 0 });
      await expectNoViolations(page, `склад ${String(width)}`);
      await settledScreenshot(page, "stock");
      if (width === 390) {
        await page.getByRole("tab", { name: "Отгрузки" }).click();
        await expect(page).toHaveURL(/view=shipments/);
        expect(await horizontalOverflow(page)).toEqual({ page: 0, main: 0 });
      }
    });
  }

  test("Входящие на 390: фильтр прокручивается вбок, все варианты доступны", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/eds/inbox");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(await horizontalOverflow(page)).toEqual({ page: 0, main: 0 });
    await expectNoViolations(page, "входящие 390");
    await settledScreenshot(page, "inbox");
    const filter = page.locator(".pf-letters-filter");
    const all = filter.getByText("Все", { exact: true });
    await all.scrollIntoViewIfNeeded();
    await all.click();
    await expect(filter.locator(".ant-segmented-item-selected")).toHaveText("Все");
    expect(await horizontalOverflow(page)).toEqual({ page: 0, main: 0 });
  });

  for (const width of [1440, 390] as const) {
    test(`витрина статусов: одна карта цветов — ${String(width)}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto("/dev/ui");
      const section = page.locator("section", { has: page.locator("#status-h") });
      await expect(section).toBeVisible();
      await expect(section.getByText("waiting · gold")).toBeVisible();
      await section.scrollIntoViewIfNeeded();
      await waitForMotionEnd(page);
      const dir = process.env["E2E_SCREENSHOT_DIR"];
      if (dir) await section.screenshot({ path: `${dir}/statuses-${String(width)}.png` });
    });
  }
});
