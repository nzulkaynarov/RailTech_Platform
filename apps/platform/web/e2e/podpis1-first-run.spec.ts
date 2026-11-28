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
    // строка шага со словом статуса в кадре, а не только верх страницы
    await row.scrollIntoViewIfNeeded();
    const item = list.getByRole("listitem").filter({ hasText: "Права подписи" });
    await expect(item).toContainText(/Сделать|Готово|Не удалось проверить|Требует/);
    await settledScreenshot(page, "first-run");
    await expectNoViolations(page, `первый запуск ${String(width)}`);
    await row.click();
    await expect(page.getByRole("heading", { level: 1, name: /Права подписи/ })).toBeVisible();
  });
}

// Реестр подписи не прочитан (EDS отказал, ошибка): шаг остаётся в списке со словом «Не удалось проверить», не пропадает.
for (const [width, height] of [
  [1512, 982],
  [390, 844],
] as const) {
  test(`Состояние: реестр подписи не прочитан — шаг со словом «Не удалось проверить» (${String(width)})`, async ({
    page,
  }) => {
    // MSW живёт в service worker — `page.route` его ответы не видит, поэтому подменяем fetch страницы
    await page.addInitScript(`(() => {
      const original = window.fetch.bind(window);
      window.fetch = (input, init) => {
        const url = input instanceof Request ? input.url : String(input);
        return /\\/eds\\/signing\\/setup-hint/.test(url)
          ? Promise.resolve(new Response(
              JSON.stringify({ code: "FORBIDDEN", message: "forbidden", source: "eds" }),
              { status: 403, headers: { "content-type": "application/json" } },
            ))
          : original(input, init);
      };
    })()`);
    await page.setViewportSize({ width, height });
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin");
    const list = page.getByRole("list", { name: "Шаги настройки" });
    const row = list.getByRole("link", { name: "Права подписи" });
    await expect(row).toBeVisible();
    await row.scrollIntoViewIfNeeded();
    await expect(list.getByRole("listitem").filter({ hasText: "Права подписи" })).toContainText(
      "Не удалось проверить",
    );
    await settledScreenshot(page, "first-run-unknown");
    await expectNoViolations(page, `первый запуск, не проверено ${String(width)}`);
  });
}
