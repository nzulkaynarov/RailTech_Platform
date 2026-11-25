import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// СЦ-7 на MSW: длинное письмо в карточке лида свёрнуто («Показать полностью»), запрос не повторяется вторым блоком;
// журнал доставки почты — назначение и причина словами. Обе ширины, axe (WCAG 2.1 AA). Данные вымышленные.
const WIDTHS = [1512, 1440, 390] as const;

async function shot(page: Page, name: string, fullPage = true): Promise<void> {
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (!dir) return;
  await page.waitForTimeout(400);
  const width = page.viewportSize()?.width ?? 0;
  await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage });
}

async function signInAt(page: Page, width: number, email: string): Promise<void> {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
  if (page.url().startsWith("http")) await page.evaluate(`window.localStorage.clear()`);
  await loginAndWait(page, email);
}

test.describe("СЦ-7: тексты и числа", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`длинное письмо в карточке лида свёрнуто — ${String(width)}`, async ({ page }) => {
      await signInAt(page, width, "manager@demo.example");
      await spaGoto(page, "/crm/leads?lead=L-2060&panel=open&tab=card");
      const panel = width < 768 ? page.getByRole("dialog") : page.locator("#pf-context-panel");
      const toggle = panel.getByRole("button", { name: "Показать полностью" });
      await expect(toggle.first()).toBeVisible();
      // запрос уже есть в сообщении: отдельным блоком «Что известно · Запрос» он не повторяется
      await expect(panel.getByText("Позиция 18:")).toHaveCount(1);
      await shot(page, "lead-panel-email");
      await toggle.first().click();
      await expect(panel.getByRole("button", { name: "Свернуть" }).first()).toBeVisible();
      // «Закрыть» раскрывается в потоке: пункты не накрывают последнее сообщение
      await panel.getByRole("button", { name: /^Закрыть: / }).click();
      const spam = page.getByRole("menuitem", { name: "Спам" });
      await expect(spam).toBeVisible();
      const lastMessage = panel.locator(".pf-crm-message").last();
      await lastMessage.scrollIntoViewIfNeeded();
      const [menuBox, messageBox] = await Promise.all([
        spam.boundingBox(),
        lastMessage.boundingBox(),
      ]);
      expect(menuBox && messageBox && menuBox.y >= messageBox.y + messageBox.height - 1).toBe(true);
      await expect(lastMessage).toBeVisible();
      await page.getByRole("menuitem", { name: "Дубль" }).scrollIntoViewIfNeeded();
      await shot(page, "lead-panel-close-menu", false);
      await expectNoViolations(page, `карточка лида ${String(width)}`);
    });

    test(`журнал доставки почты — словами, не кодами — ${String(width)}`, async ({ page }) => {
      await signInAt(page, width, "admin@demo.example");
      await spaGoto(page, "/admin/mail");
      await expect(page.getByRole("list", { name: "Журнал доставки" })).toBeVisible();
      await expect(page.getByText("CRM · Подтверждение запроса")).toBeVisible();
      await expect(page.getByText(/web_confirmation|smtp_unavailable|SMTP 550/)).toHaveCount(0);
      await page.getByRole("list", { name: "Журнал доставки" }).scrollIntoViewIfNeeded();
      await shot(page, "mail-log", false);
      await expectNoViolations(page, `журнал почты ${String(width)}`);
    });
  }
});
