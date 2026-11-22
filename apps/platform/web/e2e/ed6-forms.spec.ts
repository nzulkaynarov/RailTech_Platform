import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";
import { expectCompany, openCompany, pickAddressee } from "./support/fields";

// ЕД-6, PR-3 на MSW: компания в заявке и в заказе партнёру выбирается, а не вписывается. Заявка: название из переписки
// стоит в поле серым; компания без роли (в поиске её нет) берётся из ответа на «Завести». Заказ: компания без роли
// поставщика получает её выбором. Снимки 1440 и 390 с axe — в docs/screens/ed6-forms.
const dir = process.env["E2E_SCREENSHOT_DIR"];

async function shot(page: import("@playwright/test").Page, name: string, width: number) {
  await waitForMotionEnd(page);
  if (dir) await page.screenshot({ path: `${dir}/${name}-${String(width)}.png` });
}

for (const width of [1440, 390] as const) {
  test(
    `заявка: компания выбирается, скрытая компания берётся из ответа, ${String(width)}`,
    { tag: "@mobile" },
    async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/crm/leads?lead=L-2041&create=1&panel=open&tab=card");
      const form = page.getByRole("form", { name: "Создать заявку" });
      const field = page.getByLabel("Название компании", { exact: true });
      await expect(form.locator(".ant-select-selection-placeholder")).toHaveText(
        "ООО Демо-Логистик",
      );
      // название из переписки открывает поиск по нему: «Завести» последней строкой
      await openCompany(field);
      await expect(
        page.locator(".ant-select-item-option").getByText("Завести «ООО Демо-Логистик»"),
      ).toBeVisible();
      await shot(page, "request-company-suggest", width);
      await page.keyboard.press("Escape");

      // ИНН занят компанией без роли: поиск её не показывает, форма выбирает её из ответа, тупика нет
      await openCompany(field);
      await field.fill("Скрытая копия");
      await page.locator(".ant-select-item-option").getByText("Завести «Скрытая копия»").click();
      const sheet = page.getByRole("dialog", { name: "Новая компания" });
      await sheet.getByLabel("ИНН").fill("300000999");
      await sheet.getByRole("button", { name: "Завести" }).click();
      await expect(sheet).toBeHidden();
      await expectCompany(page, "ООО «Скрытая Компания»", "Название компании");
      await shot(page, "request-company-hidden", width);
      await expectNoViolations(page, "заявка: компания выбрана");

      // человек из карточки компании: контакт заполняется выбором
      await pickAddressee(page, "ГНИ", "ГНИ Мирабадского района", "Название компании");
      await form.getByRole("button", { name: /^Контакт/, expanded: false }).click();
      await expect(form.getByLabel("Человек из карточки компании")).toBeVisible();
      await shot(page, "request-person", width);
    },
  );

  test(
    `заказ партнёру: партнёр выбирается, компании без роли поставщика роль ставится, ${String(width)}`,
    { tag: "@mobile" },
    async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "supply@demo.example");
      await spaGoto(page, "/erp/stock/new");
      await expect(
        page.getByRole("heading", { level: 1, name: "Новый заказ партнёру" }),
      ).toBeVisible();
      const field = page.getByLabel("Партнёр", { exact: true });
      await openCompany(field);
      await field.fill("Демо");
      await expect(
        page.locator(".ant-select-item-option").getByText("АО «Демо-Путь»"),
      ).toBeVisible();
      await shot(page, "order-partner-search", width);
      await pickAddressee(page, "Демо", "АО «Демо-Путь»", "Партнёр");
      await shot(page, "order-partner-picked", width);
      await expectNoViolations(page, "заказ партнёру: партнёр выбран");
    },
  );
}
