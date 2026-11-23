import { expect, test, type Page } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ЛИД-5: в карточке лида видно, откуда он пришёл (канал словами, форма, страница, кампания) одной строкой «Откуда»,
// список лидов фильтруется по каналу. axe 0 и снимки 1440 и 390 (`E2E_SCREENSHOT_DIR=docs/screens/lid5-lead-source`).
const ORIGIN = "Веб-форма · заявка в кабинете · /new-client · кампания pos-nov";

async function filteredList(page: Page, width: number): Promise<void> {
  await loginAndWait(page, "manager@demo.example");
  await spaGoto(page, "/crm/leads?channel=web");
  await expect(page.getByRole("heading", { level: 1, name: "Лиды" })).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Открыть карточку Шахноза Демо" }).first(),
  ).toBeVisible();
  // фильтр по каналу оставляет только веб-лиды
  await expect(page.getByRole("link", { name: "Открыть карточку Азиз Демо" })).toHaveCount(0);
  await settledScreenshot(page, "leads-by-channel");
  await expectNoViolations(page, `список ${String(width)}`);
}

test.describe("ЛИД-5: откуда пришёл лид", () => {
  test.skip(({ isMobile }) => isMobile, "сценарий на десктопе; 390 — отдельный сценарий @mobile");

  test("1440: фильтр «Веб-форма» → карточка с «Откуда», axe 0", async ({ page }) => {
    await filteredList(page, 1440);
    await page.getByRole("link", { name: "Открыть карточку Шахноза Демо" }).first().click();
    const panel = page.locator("#pf-context-panel");
    await expect(panel.getByRole("heading", { name: "Шахноза Демо" })).toBeVisible();
    await expect(panel).toContainText("Откуда");
    await expect(panel).toContainText(ORIGIN);
    await settledScreenshot(page, "lead-card-origin");
    await expectNoViolations(page, "карточка 1440");
  });
});

test(
  "390: фильтр «Веб-форма» → карточка с «Откуда», axe 0",
  { tag: "@mobile" },
  async ({ page, isMobile }) => {
    test.skip(!isMobile, "узкий экран — проект mobile");
    await filteredList(page, 390);
    await page.getByRole("link", { name: "Открыть карточку Шахноза Демо" }).first().click();
    const card = page.getByRole("dialog").filter({ hasText: "Шахноза Демо" });
    await expect(card).toContainText("Откуда");
    await expect(card).toContainText(ORIGIN);
    await settledScreenshot(page, "lead-card-origin");
    await expectNoViolations(page, "карточка 390");
  },
);
