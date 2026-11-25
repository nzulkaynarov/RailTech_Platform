import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ОНБ-1.2 на MSW: в «Настройки · Telegram · Подключение» под названием канала строка «Боту нужно право приглашать»,
// когда у бота нет права. Снимки 1512, 1440 и 390 и axe 0 (`E2E_SCREENSHOT_DIR=docs/screens/onb2-team-channel`).
const WIDTHS = [1512, 1440, 390] as const;
const NEEDS = "Боту нужно право приглашать пользователей в канал.";

/** Демо-бот «с правом»; для снимка ответ состояния подменяется на «права нет» (как отдал бы CRM). */
async function withoutInviteRight(page: Page): Promise<void> {
  await page.addInitScript(`(() => {
    const original = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const response = await original(...args);
      const first = args[0];
      const url = typeof first === "string" ? first : first instanceof Request ? first.url : String(first);
      if (!url.includes("/admin/integrations/telegram") || url.includes("channels")) return response;
      const body = await response.clone().json();
      if (body && typeof body === "object" && "channel_id" in body) body.channel_can_invite = false;
      return new Response(JSON.stringify(body), { status: response.status, headers: response.headers });
    };
  })()`);
}

test("боту без права приглашать — строка под названием канала", async ({ page }) => {
  await withoutInviteRight(page);
  await loginAndWait(page, "admin@demo.example");
  await page.goto("/admin/telegram");
  await expect(page.getByText(NEEDS)).toBeVisible();
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await expect(page.getByText(NEEDS)).toBeVisible();
    await expectNoViolations(page, `telegram ${String(width)}`);
    const overflow = await page.evaluate<number>(
      "document.documentElement.scrollWidth - document.documentElement.clientWidth",
    );
    expect(overflow).toBeLessThanOrEqual(0);
    await settledScreenshot(page, "settings-telegram-needs-invite");
  }
});
