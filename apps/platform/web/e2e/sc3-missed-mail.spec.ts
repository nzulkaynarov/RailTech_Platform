import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// СЦ-3 на MSW: письма, не ушедшие, пока почта не была настроена, — «Отправить» в панели почты ставит их в очередь.
// Обе ширины, axe (WCAG 2.1 AA), снимки — `E2E_SCREENSHOT_DIR=docs/screens/sc3-mail`. Данные вымышленные.
const WIDTHS = [1440, 390] as const;
const KEY = "rt-pf-mock-integrations";

for (const width of WIDTHS) {
  test(`@mobile пропущенные письма уходят одной кнопкой · ${String(width)}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/mail");
    // Состояние мока сохраняется после первого действия; затем — три письма, не ушедшие без почты.
    await page.getByRole("button", { name: "Проверить отправку" }).click();
    await expect(page.getByText(/Тестовое письмо/).first()).toBeVisible();
    await page.evaluate(`(() => {
      const state = JSON.parse(window.localStorage.getItem(${JSON.stringify(KEY)}));
      state.smtp.missed = 3;
      window.localStorage.setItem(${JSON.stringify(KEY)}, JSON.stringify(state));
    })()`);
    await page.reload();

    const alert = page
      .getByRole("status")
      .filter({ hasText: "Не ушли, пока почта не была настроена: 3" });
    await expect(alert).toBeVisible();
    await expectNoViolations(page, "панель почты с пропущенными письмами");
    await settledScreenshot(page, "mail-missed");

    await alert.getByRole("button", { name: "Отправить" }).click();
    await expect(page.getByText("Отправлено в очередь: 3")).toBeVisible();
    await expect(page.getByText(/Не ушли, пока почта не была настроена/)).toHaveCount(0);
  });
}
