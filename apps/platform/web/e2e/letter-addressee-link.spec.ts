import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";
import { clearCompany, expectCompany, pickAddressee, openCompany } from "./support/fields";

// ЕД-6 на MSW (поле выбора компании и человека): адресат письма — компания из контрагентов (роль и ИНН в строке) и
// человек из её карточки; свободного текста нет. Снимки 1440 и 390 с axe.
const dir = process.env["E2E_SCREENSHOT_DIR"];

for (const width of [1440, 390] as const) {
  test(
    `письмо: адресат ссылкой — организация и человек, ${String(width)}`,
    { tag: "@mobile" },
    async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/eds/new?type=letter");
      await expect(page.getByRole("heading", { level: 1, name: "Исходящее письмо" })).toBeVisible();
      await expect(page.getByLabel("Кому — человек")).toBeDisabled();

      const field = page.getByLabel("Адресат (организация)", { exact: true });
      await openCompany(field);
      await field.fill("Демо");
      await expect(page.getByText("ИНН 300000777 · клиент · Узбекистан")).toBeVisible();
      await expect(page.locator(".ant-select-item-option").last()).toContainText("Завести «Демо»");
      await waitForMotionEnd(page);
      if (dir)
        await page.screenshot({ path: `${dir}/addressee-company-open-${String(width)}.png` });
      await pickAddressee(page, "Демо-Путь", "АО «Демо-Путь»");
      await expect(page.getByText("ИНН 300000777", { exact: true })).toBeVisible();
      await expect(page.getByLabel("Почта адресата")).toHaveValue("office@demo-put.example");
      await page.getByLabel("Кому — человек").click();
      await page.locator(".ant-select-item-option").filter({ hasText: "Демо Клиентов" }).click();
      await expect(page.getByLabel("Кому (должность и ФИО)")).toHaveValue(
        "Главный инженер Демо Клиентов",
      );
      // почта человека заполняет «Почту адресата»
      await expect(page.getByLabel("Почта адресата")).toHaveValue("d.klientov@demo-put.example");
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/addressee-person-${String(width)}.png` });
      await expectNoViolations(page, "адресат и человек");

      // текст в поле — только запрос: без выбора компания не появляется; очистка снимает выбор и выключает «человека»
      await openCompany(field);
      await field.fill("ГНИ Мирабадского района");
      await page.keyboard.press("Escape");
      await expectCompany(page, "АО «Демо-Путь»");
      await clearCompany(field);
      await expect(page.getByLabel("Кому — человек")).toBeDisabled();
    },
  );
}
