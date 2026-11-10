import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

const WIDTHS = [1440, 390] as const;

test.describe("Настройки · Подключения: каталог", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`каталог виден и проходит axe на ${String(width)}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin/integrations");
      await expect(page.getByRole("region", { name: "Другие сервисы" })).toBeVisible();
      await expectNoViolations(page, `connectors ${String(width)}`);
      await settledScreenshot(page, "connectors");
    });
  }
});
