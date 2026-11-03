import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// OPS-CONSOLE на MSW: в карточках «Подключений» — «Открыть» внешних кабинетов (новая вкладка, без учётных данных) и
// «Открыть консоль» внутренних сервисов только администратору; директор консолей не видит. axe и снимки 1440 и 390.
const WIDTHS = [1440, 390] as const;
const PANEL = "#pf-context-panel";

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

async function openCard(page: Page, card: string): Promise<void> {
  await spaGoto(page, `/admin/integrations?card=${card}&panel=open`);
  await expect(page.getByRole("heading", { level: 1, name: "Подключения" })).toBeVisible();
  await expect(page.locator(PANEL).locator(".ant-skeleton, [data-pf-skeleton]")).toHaveCount(0);
}

test.describe("Консоли сервисов и внешние кабинеты", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`администратор на ${String(width)}: «Открыть консоль» и кабинеты, axe`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "admin@demo.example");

      await openCard(page, "models");
      const side = page.locator(PANEL);
      await expect(
        side.getByRole("link", { name: "Консоль Anthropic — откроется в новой вкладке" }),
      ).toHaveAttribute("href", "https://console.anthropic.com/");
      // Шлюз моделей через Платформу не открывается (DECISIONS 2026-11-03) — только кабинеты провайдеров.
      await expect(side.getByRole("link", { name: /Открыть консоль/ })).toHaveCount(0);
      await expectNoViolations(page, `models ${String(width)}`);
      await settledScreenshot(page, "admin-models");

      await openCard(page, "erp");
      const erpConsole = side.getByRole("link", {
        name: "Открыть консоль «панель базы» в новой вкладке",
      });
      await expect(erpConsole).toHaveAttribute("href", "/console/erp/admin/");
      await expect(erpConsole).toHaveAttribute("target", "_blank");
      await expectNoViolations(page, `erp ${String(width)}`);
      await settledScreenshot(page, "admin-erp");

      await openCard(page, "telegram");
      await expect(
        side.getByRole("link", { name: "BotFather — откроется в новой вкладке" }),
      ).toHaveAttribute("href", "https://t.me/BotFather");
      await expectNoViolations(page, `telegram ${String(width)}`);
      await settledScreenshot(page, "admin-telegram");

      await openCard(page, "storage");
      await expect(
        side.getByRole("link", { name: "Папка на Яндекс Диске — откроется в новой вкладке" }),
      ).toBeVisible();
      await expectNoViolations(page, `storage ${String(width)}`);
    });

    test(`директор на ${String(width)}: консолей нет, кабинеты есть, axe`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");

      await openCard(page, "models");
      const side = page.locator(PANEL);
      await expect(
        side.getByRole("link", { name: "Консоль Anthropic — откроется в новой вкладке" }),
      ).toBeVisible();
      await expect(side.getByRole("link", { name: /Открыть консоль/ })).toHaveCount(0);
      await openCard(page, "erp");
      await expect(side.getByRole("heading", { level: 3, name: "ERP" })).toBeVisible();
      await expect(side.getByRole("link", { name: /Открыть консоль/ })).toHaveCount(0);
      await expectNoViolations(page, `director erp ${String(width)}`);
      await settledScreenshot(page, "director-erp");
    });
  }
});
