import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot } from "./support/app";
import { expectNoViolations } from "./support/axe";

// Окно «Создать» (план 2026-11-12 п. 0.1): три группы с подписями, пункт открывает форму; лид — новая форма.
test.describe("Окно «Создать»", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("на 1440: группы и подписи; «Лид» открывает форму, созданный лид — карточкой", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "manager@demo.example");
    await page.getByRole("button", { name: "Создать", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Создать" });
    await expect(dialog.getByRole("heading", { name: "Продажи" })).toBeVisible();
    await expect(dialog.getByRole("link", { name: /^Внутренний документ/ })).toBeVisible();
    await expectNoViolations(page, "create 1440");
    await settledScreenshot(page, "create-window");

    await dialog.getByRole("link", { name: /^Лид/ }).click();
    const form = page.getByRole("form", { name: "Новый лид" });
    await expect(form).toBeVisible();
    await form.getByLabel("Имя").fill("Азиз Каримов");
    await form.getByLabel("Телефон").fill("+998 90 555 11 22");
    await form.getByLabel("Что нужно").fill("Колёсные пары, 10 шт.");
    await expectNoViolations(page, "new lead 1440");
    await settledScreenshot(page, "create-new-lead");
    await form.getByRole("button", { name: "Создать лид" }).click();
    await expect(page).toHaveURL(/lead=L-\d{4}/);
  });

  test("на 1440: «Внутренний документ» ведёт в форму служебной записки", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "manager@demo.example");
    await page.getByRole("button", { name: "Создать", exact: true }).click();
    await page
      .getByRole("dialog", { name: "Создать" })
      .getByRole("link", { name: /^Внутренний документ/ })
      .click();
    await expect(page).toHaveURL(/\/eds\/new\?type=memo$/);
  });

  test("на 390: окно на весь экран из меню раздела", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "manager@demo.example");
    await page.getByRole("button", { name: "Меню" }).click();
    await page.getByRole("button", { name: "Создать", exact: true }).click();
    await expect(
      page.getByRole("dialog", { name: "Создать" }).getByRole("link", { name: /^Заявка/ }),
    ).toBeVisible();
    await expectNoViolations(page, "create 390");
    await settledScreenshot(page, "create-window");
  });
});
