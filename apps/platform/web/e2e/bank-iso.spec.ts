import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ADR-0029 на MSW: счёт своей компании за рубежом — IBAN и SWIFT проверяются при вводе, страна банка — из SWIFT.
// Снимки 1440 и 390 с axe — E2E_SCREENSHOT_DIR (docs/screens/bank-iso).
const WIDTHS = [1440, 390];

test.describe("банковский счёт по стандартам ISO", () => {
  for (const width of WIDTHS) {
    test(`счёт за рубежом: IBAN, SWIFT, посредник, ${String(width)}`, async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin/company");
      await page.getByRole("button", { name: /Банковские счета/ }).click();
      await page.getByRole("button", { name: "Добавить счёт" }).first().click();
      const dialog = page.getByRole("region", { name: "Новый банковский счёт" });
      await dialog.getByText("За рубежом", { exact: true }).click();
      await dialog.getByLabel("SWIFT/BIC", { exact: true }).fill("COBADEFF");
      await dialog.getByLabel("IBAN или номер счёта").fill("DE89 3704 0044 0532 0130 01");
      await dialog.getByLabel("Владелец счёта латиницей").fill("Demo LLC");
      await dialog.getByRole("button", { name: "Сохранить" }).click();
      await expect(
        dialog.getByText("IBAN не проходит проверку: длина или контрольные цифры"),
      ).toBeVisible();
      await waitForMotionEnd(page);
      const dir = process.env["E2E_SCREENSHOT_DIR"];
      if (dir)
        await page.screenshot({
          path: `${dir}/platform-bank-abroad-${String(width)}.png`,
          fullPage: true,
        });
      await expectNoViolations(page, `счёт за рубежом ${String(width)}`);

      await dialog.getByLabel("IBAN или номер счёта").fill("DE89 3704 0044 0532 0130 00");
      await dialog.getByRole("button", { name: "Сохранить" }).click();
      await expect(page.getByText("DE89 3704 0044 0532 0130 00 · DE")).toBeVisible();
    });
  }
});
