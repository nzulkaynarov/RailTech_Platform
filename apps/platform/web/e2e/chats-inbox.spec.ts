import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

const WIDTHS = [1440, 390] as const;

test.describe("Органайзер · Чаты", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`открывается и проходит axe на ${String(width)}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/chats");
      await expect(page.getByRole("heading", { level: 1, name: "Чаты" })).toBeVisible();
      await expect(page.locator(".pf-chats .cs-message-input")).toBeVisible();
      await expectNoViolations(page, `chats ${String(width)}`);
      await settledScreenshot(page, "chats");
    });
  }
});
