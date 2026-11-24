import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ЕД-3, ЕД-4 (волна 24, хвосты): люди и компании в органайзере и строки принятого — общие ячейки со снимками 1512 и 390.
// «Люди» (компания с логотипом, ответственный за лид), календарь (в нём людей нет, снимок для сверки), журнал приёмок
// склада (позиция с миниатюрой вместо текста через «;»), заказы партнёрам (логотип партнёра). Поручения — в p8b-instructions.
const YEAR = String(new Date().getFullYear());
const ORDER = `ЗП-${YEAR}-029`;

async function at(page: Page, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
}

test.describe("ЕД-3 и ЕД-4: хвосты органайзера и склада", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of [1512, 390] as const) {
    test(`${String(width)}: люди, календарь, приёмки, заказы партнёрам`, async ({ page }) => {
      await at(page, width);
      await loginAndWait(page, "director@demo.example");

      await spaGoto(page, "/chats/contacts");
      await expect(page.getByRole("heading", { level: 1, name: "Люди" })).toBeVisible();
      await page.locator(".ant-segmented-item").filter({ hasText: "Люди клиентов" }).click();
      await expect(page.locator(".pf-entity__pic--square").first()).toBeVisible();
      await settledScreenshot(page, "organizer-contacts");
      await expectNoViolations(page, `контакты ${String(width)}`);
      await page.locator(".ant-segmented-item").filter({ hasText: "Лиды" }).click();
      await expect(page.locator(".pf-entity").first()).toBeVisible();
      await settledScreenshot(page, "organizer-leads");
      await expectNoViolations(page, `лиды ${String(width)}`);

      await spaGoto(page, "/chats/calendar");
      await expect(page.getByRole("heading", { level: 1, name: "Календарь" })).toBeVisible();
      await expect(page.locator(".fc")).toBeVisible();
      await settledScreenshot(page, "organizer-calendar");
      await expectNoViolations(page, `календарь ${String(width)}`);

      await spaGoto(page, "/erp/stock?view=orders");
      await expect(page.locator(".pf-entity").first()).toBeVisible();
      await settledScreenshot(page, "stock-orders");
      await expectNoViolations(page, `заказы партнёрам ${String(width)}`);

      // принять заказ, чтобы в журнале была завершённая приёмка
      await spaGoto(page, `/erp/stock/${encodeURIComponent(ORDER)}`);
      await page.getByRole("button", { name: "Принять товар" }).click();
      const receive = page.getByRole("dialog", { name: `Принять товар по заказу ${ORDER}` });
      await receive.getByRole("textbox", { name: /Ячейка для/ }).fill("A-03-2");
      await receive.getByRole("button", { name: "Принять" }).click();
      await expect(page.getByText("Товар принят")).toBeVisible();

      await spaGoto(page, "/erp/stock?view=receipts");
      const journal = page.getByRole("list", { name: "Последние приёмки" });
      await expect(journal.locator(".pf-stock-receipt-lines .pf-entity").first()).toBeVisible();
      await expect(journal.locator('img[src*="/thumbnail?v="]').first()).toBeVisible();
      await settledScreenshot(page, "stock-receipts-journal");
      await expectNoViolations(page, `журнал приёмок ${String(width)}`);
    });
  }
});
