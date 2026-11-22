import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ЕВ-0 (часть 1, десктоп): «Люди» в общей рамке без кнопок без действия; у формы письма нет кнопки и пустого окна;
// «Налоги и валюты» с одним полем НДС и одной формой курса. Снимки 1440 и 390 с axe.
const WIDTHS = [1440, 390] as const;
const size = (width: number) => ({ width, height: width === 390 ? 844 : 900 });

test.describe("ЕВ-0: быстрые правки", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`Люди: таблица в рамке списка, без «Написать» и «Позвонить», ${String(width)}`, async ({
      page,
    }) => {
      await page.setViewportSize(size(width));
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/chats/contacts?panel=open");
      await expect(page.getByRole("heading", { level: 1, name: "Люди" })).toBeVisible();
      const row = page.locator(".ant-card .pf-people-table tbody tr").first();
      await expect(row).toBeVisible();
      await expect(page.getByTestId("panel-toggle")).toBeHidden();
      await expect(page.getByText("Объект не выбран")).toHaveCount(0);
      await expect(page.getByRole("columnheader").first()).toHaveCSS("text-align", "left");
      await expectNoViolations(page, `people ${String(width)}`);
      await settledScreenshot(page, `people-${String(width)}`);
      await page.getByRole("button", { name: "Демо Клиентов" }).first().click();
      const card = page.getByRole("dialog", { name: "Демо Клиентов" });
      await expect(card).toBeVisible();
      await expect(card.getByRole("button", { name: /Написать|Позвонить/ })).toHaveCount(0);
      await expectNoViolations(page, `people card ${String(width)}`);
      await settledScreenshot(page, `people-card-${String(width)}`);
    });

    test(`Новое письмо: кнопки окна и пустого окна нет, ${String(width)}`, async ({ page }) => {
      await page.setViewportSize(size(width));
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/eds/new?type=letter&panel=open");
      await expect(page.getByRole("heading", { level: 1, name: "Исходящее письмо" })).toBeVisible();
      await expect(page.getByTestId("panel-toggle")).toBeHidden();
      await expect(page.getByRole("button", { name: /Показать панель|Скрыть панель/ })).toHaveCount(
        0,
      );
      await expect(page.getByText("Объект не выбран")).toHaveCount(0);
      await expect(page.getByRole("complementary", { name: "Боковое окно" })).toHaveCount(0);
      await expect(page.getByLabel("Строка адресата")).toBeVisible();
      await expectNoViolations(page, `new letter ${String(width)}`);
      await settledScreenshot(page, `new-letter-${String(width)}`);
    });

    test(`Налоги и валюты: одно поле НДС и одна форма курса, ${String(width)}`, async ({
      page,
    }) => {
      await page.setViewportSize(size(width));
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/admin/taxes?panel=open");
      await expect(page.getByRole("heading", { level: 1, name: "Налоги и валюты" })).toBeVisible();
      await expect(page.getByTestId("panel-toggle")).toBeHidden();
      await expect(page.getByText("Объект не выбран")).toHaveCount(0);
      await expect(page.getByLabel(/Ставка НДС/)).toHaveCount(1);
      await expect(page.getByLabel("Ставка НДС в новом КП, %")).toBeVisible();
      await expect(page.getByRole("form", { name: "Ручной ввод курса" })).toHaveCount(1);
      await expect(page.getByRole("button", { name: "Ввести курс USD" })).toHaveCount(0);
      await expectNoViolations(page, `taxes ${String(width)}`);
      await settledScreenshot(page, `taxes-${String(width)}`);
    });
  }
});
