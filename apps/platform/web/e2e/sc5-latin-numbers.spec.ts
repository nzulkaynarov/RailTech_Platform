import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";
import { openStep } from "./support/fields";

// СЦ-5 «Латиница в номерах» на MSW: обозначение вида номера принимает только латиницу и цифры (ошибка под полем), а карточка
// документа EDS показывает текущий номер проекта из ERP (PRJ-…), а не сохранённую копию. Снимки — `E2E_SCREENSHOT_DIR`.
const WIDTHS = [1440, 390] as const;

for (const width of WIDTHS) {
  test.describe(`СЦ-5: латиница в номерах, ${String(width)} px`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    });

    test("обозначение вида номера: кириллица даёт ошибку под полем", async ({ page }) => {
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/admin/numbering");
      await expect(page.getByRole("heading", { level: 1, name: "Нумерация" })).toBeVisible();

      const label = page.getByLabel("Заявка", { exact: true });
      await label.scrollIntoViewIfNeeded();
      await label.fill("ВХ");
      await expect(
        page.getByText("Только латинские буквы A-Z и цифры", { exact: true }),
      ).toBeVisible();

      await label.fill("IN");
      await expect(
        page.getByText("Только латинские буквы A-Z и цифры", { exact: true }),
      ).toBeHidden();
      await label.fill("ВХ");
      await expect(
        page.getByText("Только латинские буквы A-Z и цифры", { exact: true }),
      ).toBeVisible();

      await expectNoViolations(page, `numbering-latin ${String(width)}`);
      await settledScreenshot(page, "numbering-latin");
    });

    test("карточка документа показывает текущий номер проекта из ERP", async ({ page }) => {
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/eds/new?type=memo");
      await expect(
        page.getByRole("heading", { level: 1, name: "Внутренний документ" }),
      ).toBeVisible();
      await openStep(page, "О чём");
      await page.getByLabel("Тема").fill("Закупка рельсов");
      await page.getByLabel("Связь с проектом").click();
      await page.getByLabel("Связь с проектом").fill("рельс");
      await page.getByTitle(/PRJ-2026-104 · Поставка рельсов Р65/).click();
      await openStep(page, "Текст и вложения");
      await page.getByLabel("Текст", { exact: true }).fill("Прошу согласовать закупку.");
      await openStep(page, "Проверка и отправка");
      await page.getByRole("button", { name: "Отправить на согласование" }).click();

      await expect(page).toHaveURL(/doc=/);
      await expect(page.getByText("PRJ-2026-104", { exact: true })).toBeVisible();
      await expect(page.getByText("ЗВ-2026-104")).toHaveCount(0);

      await expectNoViolations(page, `deal-number ${String(width)}`);
      await settledScreenshot(page, "deal-number");
    });
  });
}
