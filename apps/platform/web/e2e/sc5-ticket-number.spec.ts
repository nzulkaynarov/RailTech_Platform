import { type Page, expect, test } from "@playwright/test";

import { login, loginAndWait, openAvatarMenu, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// СЦ-5: обозначение обращения в «Нумерации» и номер TK-0001 в карточке обращения (MSW), 1440 и 390, axe.
const WIDTHS = [1440, 390] as const;

async function resize(page: Page, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
}

test.describe("СЦ-5: номера обращений на латинице", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`нумерация: поле «Обращение» на ${String(width)}`, async ({ page }) => {
      await resize(page, width);
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/admin/company?tab=numbering");
      await expect(
        page.getByRole("heading", { level: 2, name: "Нумерация документов" }),
      ).toBeAttached();
      await expect(page.getByLabel("Обращение")).toHaveValue("TK");
      await page.getByLabel("Обращение").scrollIntoViewIfNeeded();
      await expectNoViolations(page, `numbering ${String(width)}`);
      await settledScreenshot(page, `sc5-numbering-ticket-${String(width)}`);
    });

    test(`карточка обращения с номером TK-0001 на ${String(width)}`, async ({ page }) => {
      await resize(page, width);
      // обращение создаёт сотрудник, открывает администратор
      await loginAndWait(page, "manager@demo.example");
      await page.goto("/admin/org?view=list");
      await page.getByRole("button", { name: "Написать администратору" }).click();
      const dialog = page.getByRole("dialog", { name: "Написать администратору" });
      await dialog.getByRole("textbox", { name: "Что случилось" }).fill("Нужен доступ");
      await dialog.getByRole("button", { name: "Отправить" }).click();
      await page
        .getByRole("dialog", { name: /отправлено/ })
        .getByRole("button", { name: "Закрыть", exact: true })
        .click();
      await openAvatarMenu(page);
      await page.getByRole("menuitem", { name: "Выйти" }).click();
      await expect(page).toHaveURL(/\/login/);
      await login(page, "admin@demo.example");
      await expect(page).toHaveURL(/\/dashboard\/queue$/);
      await page.goto("/admin/tickets/TK-0001?panel=open&tab=card");
      await expect(page.getByRole("textbox", { name: "Ваш ответ" })).toBeVisible();
      await expect(page.getByText("TK-0001").first()).toBeVisible();
      await expectNoViolations(page, `ticket card ${String(width)}`);
      await settledScreenshot(page, `sc5-ticket-card-${String(width)}`);
    });
  }
});
