import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// CHAT-1 (ADR-0023): чат кабинета в очереди «Сообщения» на MSW — беседа из кабинета со значком канала в списке, имя
// контакта и метка КП у сообщения, подпись «Уйдёт клиенту в кабинет» под полем ответа. axe 0 и снимки 1440 и 390 для PR
// (`E2E_SCREENSHOT_DIR=docs/screens/chat-1`, имена с префиксом `platform-`).
const WIDTHS = [1440, 390] as const;

async function shot(page: Page, name: string): Promise<void> {
  await page.mouse.move(0, 0);
  await settledScreenshot(page, `platform-${name}`);
}

test.describe("CHAT-1: беседа из кабинета", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`${String(width)} px: список, тред с меткой КП, ответ уйдёт в кабинет`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "manager@demo.example");

      await spaGoto(page, "/crm/messages");
      const list = page.getByRole("navigation", { name: "Диалоги, которые ждут ответа" });
      await expect(list.getByRole("img", { name: "Канал: Кабинет" })).toBeVisible();
      await expect(list.getByRole("link", { name: /^ООО «Пример-Снаб»/ })).toBeVisible();
      await shot(page, "messages-list");
      await expectNoViolations(page, `список ${String(width)}`);

      await list.getByRole("link", { name: /^ООО «Пример-Снаб»/ }).click();
      await expect(page).toHaveURL(/lead=L-2070/);
      await expect(
        page.getByRole("heading", { level: 2, name: "ООО «Пример-Снаб»" }),
      ).toBeVisible();
      await expect(
        page.locator(".pf-msg-bubble", { hasText: "Можно ли поставку разбить на две партии?" }),
      ).toBeVisible();
      await expect(
        page.getByLabel("Написал со страницы документа: КП KP-2026-0042").first(),
      ).toBeVisible();
      await expect(page.getByText("Уйдёт клиенту в кабинет")).toBeVisible();
      if (width === 1440) {
        await expect(page.locator("#pf-context-panel")).toContainText(
          "нет — ответ в кабинет можно, в Telegram нельзя",
        );
      }
      const overflow = await page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth",
      );
      expect(overflow).toBeLessThanOrEqual(0);
      await shot(page, "messages-cabinet-thread");
      await expectNoViolations(page, `тред ${String(width)}`);
    });
  }
});
