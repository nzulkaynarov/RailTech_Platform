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
      await expect(page.getByRole("heading", { level: 2, name: "Заявки" })).toBeVisible();
      const field = page.getByRole("combobox", { name: "Резолюция перед расчётом" });
      await field.scrollIntoViewIfNeeded();
      await expect(field).toBeVisible();
      await expect(page.getByText("У каждой заявки", { exact: true })).toBeVisible();
      await expect(page.getByText(/Резолюцию дают держатели права/)).toBeVisible();
      await settledScreenshot(page, "res1-sales-default");

      await page.locator(".ant-select", { has: field }).click();
      await page.locator(".ant-select-item-option", { hasText: "Не нужна" }).click();
      await page.getByRole("button", { name: "Сохранить правило" }).click();
      await expect(page.getByText("Сохранено")).toBeVisible();
      await expect(page.getByText("Не нужна", { exact: true })).toBeVisible();
      await settledScreenshot(page, "res1-sales-never");

      await expectNoViolations(page, "резолюция перед расчётом в настройках продаж");

      // Форма «Создать заявку» говорит то же, что настроено
      await spaGoto(page, "/crm/leads?lead=L-2041&create=1&panel=open&tab=card");
      const review = page.getByText("Проверка и отправка", { exact: true }).first();
      // На 390 px форма — лист поверх вкладок: обычный клик перехватывает слой вкладок
      if (width < 600) await review.dispatchEvent("click");
      else await review.click();
      await expect(page.getByText("Заявка сразу уйдёт в расчёт ответственному.")).toBeVisible();
      if (width >= 600) await settledScreenshot(page, "res1-request-form-never");
      await expectNoViolations(page, "форма заявки: расчёт сразу");
      const overflow = await page.evaluate<boolean>(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth",
      );
      expect(overflow, "горизонтальной прокрутки нет").toBe(false);
    });

    test("расчёт без резолюции: задание без блока резолюции, срок виден", async ({ page }) => {
      await page.addInitScript(`window.localStorage.setItem("rt-pf-mock-no-resolution", "1");`);
      await loginAndWait(page, "supply@demo.example");
      if (width < 600) {
        await spaGoto(page, `/erp/calc/${encodeURIComponent("ЗВ-2026-097")}`);
        await page.getByRole("button", { name: "Задание и визы" }).click();
      } else {
        await spaGoto(page, "/erp/requests");
        await page.getByRole("link", { name: /Показать задание по заявке ЗВ-2026-097/ }).click();
      }
      await expect(
        page.getByText("Резолюция не требовалась — расчёт поставлен ответственному сразу."),
      ).toBeVisible();
      await expect(page.getByText(/Посчитать переводы со склада/)).toHaveCount(0);
      await expect(page.getByText("Файл заявки загружается…")).toBeVisible();
      await settledScreenshot(page, "res1-calc-task-direct");
      await expectNoViolations(page, "задание расчёта без резолюции");
    });
  });
}
