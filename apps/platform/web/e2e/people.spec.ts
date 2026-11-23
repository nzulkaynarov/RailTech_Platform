import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

const WIDTHS = [1440, 390] as const;

test.describe("Органайзер · Люди", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`открывается и проходит axe на ${String(width)}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/chats/contacts");
      await expect(page.getByRole("heading", { level: 1, name: "Люди" })).toBeVisible();
      await expect(page.locator(".pf-people tbody tr").first()).toBeVisible();
      await expectNoViolations(page, `people ${String(width)}`);
      await settledScreenshot(page, "people");
    });

    test(`карточка коллеги: контакты скрыты, «Показать контакты» открывает их, ${String(width)}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "accountant@demo.example");
      await spaGoto(page, "/chats/contacts");
      await expect(page.locator(".pf-people tbody tr").first()).toBeVisible();
      // бухгалтер видит коллег: решение 10.11 — имя, должность и роли открыты всем
      await page
        .getByRole("button", { name: "Сотрудники" })
        .or(page.getByText("Сотрудники", { exact: true }))
        .first()
        .click();
      await page.locator(".pf-people-name").first().click();
      const card = page.locator(".pf-people-card");
      await expect(card).toBeVisible();
      await expect(card.getByText("•••").first()).toBeVisible();
      await expectNoViolations(page, `people card ${String(width)}`);
      await settledScreenshot(page, "people-card");
      await card.getByRole("button", { name: "Показать контакты" }).click();
      await expect(card.getByRole("link", { name: /@demo\.example$/ })).toBeVisible();
      await expectNoViolations(page, `people revealed ${String(width)}`);
      await settledScreenshot(page, "people-revealed");
    });
  }
});
