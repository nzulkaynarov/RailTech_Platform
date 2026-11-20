import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// СЦ-5: строка «Прежний номер» в карточке письма и карточке документа — только если номер менялся; снимки 1440 и 390 и axe.
const WIDTHS = [1440, 390];

for (const width of WIDTHS) {
  test.describe(`Прежний номер, ${String(width)} px`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
    });

    test("карточка письма", async ({ page }) => {
      await spaGoto(page, `/eds/inbox/${encodeURIComponent("ВХ-100/26")}`);
      await expect(page.getByRole("heading", { level: 1, name: "Письмо ВХ-100/26" })).toBeVisible();
      await expect(page.getByText("Прежний номер")).toBeVisible();
      await expect(page.getByText("ВХ-100", { exact: true })).toBeVisible();
      await settledScreenshot(page, "letter-previous-number");
      await expectNoViolations(page, `письмо ${String(width)}`);
    });

    test("карточка документа", async ({ page }) => {
      await spaGoto(page, "/eds/documents?scope=all");
      await page.getByRole("link", { name: "Открыть документ: Командировка в Самарканд" }).click();
      await expect(page.getByText("Прежний номер")).toBeVisible();
      await expect(page.getByText("СЗ-028", { exact: true })).toBeVisible();
      await settledScreenshot(page, "document-previous-number");
      await expectNoViolations(page, `документ ${String(width)}`);
    });
  });
}
