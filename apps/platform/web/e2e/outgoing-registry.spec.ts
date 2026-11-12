import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// «Исходящие» по стадии (план 2026-11-12 п. 0.9, находка FR-5): одобренное КП ждёт клиента — в «Исходящих», с суммой
// и «Открыть КП»; в «Архиве» его нет.
test.describe("Реестр «Исходящие»", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of [1440, 390] as const) {
    test(`${String(width)}: КП, договор и акт в «Исходящих» с суммами`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/eds/documents?box=outgoing&scope=all");
      await expect(page.getByText("КП · Колёсные пары, 10 шт.").first()).toBeVisible();
      await expect(page.getByText("197 993 600 сум").first()).toBeVisible();
      await expect(page.getByText("ДОГ-2026/105").first()).toBeVisible();
      await expectNoViolations(page, `outgoing ${String(width)}`);
      await settledScreenshot(page, "outgoing-registry");

      await spaGoto(page, "/eds/documents?box=archive&scope=all");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.getByText("КП · Колёсные пары, 10 шт.")).toHaveCount(0);
    });
  }
});
