import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot } from "./support/app";
import { expectNoViolations } from "./support/axe";

test.describe("Единая кнопка «Создать»", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("на 1440 открывает виды роли, служебка ведёт в форму", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "manager@demo.example");
    await page.getByRole("button", { name: "Создать", exact: true }).click();
    await expect(page.getByRole("menuitem", { name: "Служебная записка" })).toBeVisible();
    await expectNoViolations(page, "create 1440");
    await settledScreenshot(page, "create-menu");
    await page.getByRole("menuitem", { name: "Служебная записка" }).click();
    await expect(page).toHaveURL(/\/eds\/new\?type=memo$/);
  });

  test("на 390 кнопка в меню раздела", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "manager@demo.example");
    await page.getByRole("button", { name: "Меню" }).click();
    await page.getByRole("button", { name: "Создать", exact: true }).click();
    await expect(page.getByRole("menuitem", { name: "Служебная записка" })).toBeVisible();
    await expectNoViolations(page, "create 390");
    await settledScreenshot(page, "create-menu");
  });
});
