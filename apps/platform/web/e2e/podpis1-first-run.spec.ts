import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ПОДПИСЬ-1 (стенд 2026-11-28): в «Первом запуске» есть шаг «Права подписи» — по реестру на сегодня, со ссылкой на экран.
// Снимки для приёмки — E2E_SCREENSHOT_DIR (1512×982 и 390), MSW.
for (const [width, height] of [
  [1512, 982],
  [390, 844],
] as const) {
  test(`Состояние: шаг «Права подписи» ведёт на реестр (${String(width)})`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin");
    const list = page.getByRole("list", { name: "Шаги настройки" });
    const row = list.getByRole("link", { name: "Права подписи" });
    await expect(row).toBeVisible();
    await expect(row).toHaveAttribute("href", "/admin/signing");
    await settledScreenshot(page, "first-run");
    await expectNoViolations(page, `первый запуск ${String(width)}`);
    await row.click();
    await expect(page.getByRole("heading", { level: 1, name: /Права подписи/ })).toBeVisible();
  });
}
