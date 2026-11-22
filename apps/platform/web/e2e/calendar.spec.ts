import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

const WIDTHS = [1440, 390] as const;

test.describe("Органайзер · Календарь", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`открывается и проходит axe на ${String(width)}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/chats/calendar");
      await expect(page.getByRole("heading", { level: 1, name: "Календарь" })).toBeVisible();
      await expect(page.getByRole("checkbox", { name: "Документы" })).toBeVisible();
      await expect(page.locator(".fc")).toBeVisible();
      await expectNoViolations(page, `calendar ${String(width)}`);
      await settledScreenshot(page, "calendar");
    });
  }

  for (const width of WIDTHS) {
    test(`ссылка для календаря в профиле: выдать, сменить, axe на ${String(width)}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/chats/calendar");
      await page.getByRole("button", { name: "Ссылка на календарь" }).click();
      await expect(page).toHaveURL(/\/me\?part=notifications$/);
      const block = page.getByTestId("profile-calendar-link");
      await expect(block.getByText("Ссылки пока нет.")).toBeVisible();
      await block.getByRole("button", { name: "Получить ссылку" }).click();
      const field = block.getByLabel("Ссылка для календаря");
      await expect(field).toHaveValue(/\/api\/v1\/calendar\/.+\.ics$/);
      await expect(
        block.getByText("Сроки обновляются, когда вы заходите в Платформу."),
      ).toBeVisible();
      await expectNoViolations(page, `calendar link ${String(width)}`);
      await block.getByRole("button", { name: "Сменить ссылку" }).scrollIntoViewIfNeeded();
      await settledScreenshot(page, "calendar-link");
      const first = await field.inputValue();
      await block.getByRole("button", { name: "Сменить ссылку" }).click();
      await page.getByRole("button", { name: "Сменить ссылку" }).last().click();
      await expect(field).not.toHaveValue(first);
    });
  }
});
