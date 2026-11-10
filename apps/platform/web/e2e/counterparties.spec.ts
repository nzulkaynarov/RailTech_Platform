import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

const WIDTHS = [1440, 390] as const;

test.describe("Контакты · Контрагенты", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`единый список и фильтр на ${String(width)}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/crm/clients");
      await expect(page.getByRole("heading", { level: 1, name: "Контрагенты" })).toBeVisible();
      await expect(page.getByText("Партнёры", { exact: true })).toBeVisible();
      await expectNoViolations(page, `counterparties ${String(width)}`);
      await settledScreenshot(page, "counterparties");
    });
  }
});
