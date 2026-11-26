import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// КОНТР-1а: лид известного контакта показан вместе с компанией, поле карточки — «Компания», а не «Клиент».
// axe 0, снимки 1512, 1440 и 390 (`E2E_SCREENSHOT_DIR=docs/screens/kontr1a-lead-company`).
const COMPANY = "ООО Рельс-Сервис Демо";

test.describe("КОНТР-1а: компания рядом с лидом", () => {
  test.skip(({ isMobile }) => isMobile, "сценарий на десктопе; 390 — отдельный сценарий @mobile");

  for (const width of [1512, 1440]) {
    test(`${String(width)}: в строке компания, в карточке «Компания» со ссылкой, axe 0`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/crm/leads");
      const link = page.getByRole("link", { name: "Открыть карточку Бобур Снабженцев" }).first();
      await expect(link).toBeVisible();
      await expect(page.getByText(`(${COMPANY})`).first()).toBeVisible();
      await settledScreenshot(page, `leads-list-${String(width)}`);
      await expectNoViolations(page, `список ${String(width)}`);
      await link.click();
      const panel = page.locator("#pf-context-panel");
      await expect(panel.getByRole("heading", { name: "Бобур Снабженцев" })).toBeVisible();
      await expect(panel.locator("dt", { hasText: /^Компания$/ }).first()).toBeVisible();
      await expect(panel.locator("dt", { hasText: /^Клиент$/ })).toHaveCount(0);
      await expect(panel.getByRole("link", { name: COMPANY })).toBeVisible();
      await settledScreenshot(page, `lead-card-${String(width)}`);
      await expectNoViolations(page, `карточка ${String(width)}`);
    });
  }
});

test(
  "390: в строке компания, в карточке «Компания», axe 0",
  { tag: "@mobile" },
  async ({ page, isMobile }) => {
    test.skip(!isMobile, "узкий экран — проект mobile");
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/crm/leads");
    await expect(page.getByText(`(${COMPANY})`).first()).toBeVisible();
    await settledScreenshot(page, "leads-list-390");
    await expectNoViolations(page, "список 390");
    await page.getByRole("link", { name: "Открыть карточку Бобур Снабженцев" }).first().click();
    const card = page.getByRole("dialog").filter({ hasText: "Бобур Снабженцев" });
    await expect(card.locator("dt", { hasText: /^Компания$/ }).first()).toBeVisible();
    await expect(card.locator("dt", { hasText: /^Клиент$/ })).toHaveCount(0);
    await settledScreenshot(page, "lead-card-390");
    await expectNoViolations(page, "карточка 390");
  },
);
