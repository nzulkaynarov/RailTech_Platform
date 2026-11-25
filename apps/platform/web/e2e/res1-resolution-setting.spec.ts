import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// РЕЗ-1: «Резолюция перед расчётом» — настройка компании в «Правила работы · Продажи», а не зашитый шаг.
// По умолчанию «У каждой заявки» (как раньше); выбор сохраняется. Ноутбук 14″ (1512), 1440 и 390 px, axe.
const SIZES = [
  { width: 1512, height: 982 },
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
] as const;

for (const { width, height } of SIZES) {
  test.describe(`${String(width)} px`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize({ width, height });
    });

    test("настройки «Продажи»: резолюция перед расчётом выбирается и сохраняется", async ({
      page,
    }) => {
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/admin/sales");
      const field = page.getByRole("combobox", { name: "Резолюция перед расчётом" });
      await field.scrollIntoViewIfNeeded();
      await expect(field).toBeVisible();
      await expect(page.getByText("У каждой заявки", { exact: true })).toBeVisible();
      await expect(page.getByText(/Резолюцию дают держатели права/)).toBeVisible();
      await settledScreenshot(page, "res1-sales-default");

      await page.locator(".ant-select", { has: field }).click();
      await page.locator(".ant-select-item-option", { hasText: "Не нужна" }).click();
      await page.getByRole("button", { name: "Сохранить условия" }).click();
      await expect(page.getByText("Сохранено")).toBeVisible();
      await expect(page.getByText("Не нужна", { exact: true })).toBeVisible();
      await settledScreenshot(page, "res1-sales-never");

      await expectNoViolations(page, "резолюция перед расчётом в настройках продаж");
      const overflow = await page.evaluate<boolean>(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth",
      );
      expect(overflow, "горизонтальной прокрутки нет").toBe(false);
    });
  });
}
