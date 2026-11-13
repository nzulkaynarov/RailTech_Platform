import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

const WIDTHS = [1440, 390] as const;

test.describe("Органайзер · Люди", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`открывается и проходит axe на ${String(width)}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/chats/contacts");
      await expect(page.getByRole("heading", { level: 1, name: "Люди" })).toBeVisible();
      await expect(page.locator(".pf-people tbody tr").first()).toBeVisible();
      await expectNoViolations(page, `people ${String(width)}`);
      await settledScreenshot(page, "people");
    });
  }
});
