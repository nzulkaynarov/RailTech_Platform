import { expect, test } from "@playwright/test";

import { loginAndWait, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ДВ-4 на MSW: «Профиль · Безопасность» — включить вход с кодом (QR, код, резервные коды), затем вход: пароль → код →
// «запомнить устройство» → следующий вход без кода. Код из приложения на моках — 123456. Снимки 1440 и 390 с axe.
const dir = process.env["E2E_SCREENSHOT_DIR"];

for (const width of [1440, 390] as const) {
  test(`вход с кодом из приложения, ${String(width)}`, { tag: "@mobile" }, async ({ page }) => {
    test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "admin@demo.example");
    await page.goto("/me?part=security");
    const section = page.getByTestId("profile-2fa").last();
    await section.getByRole("button", { name: "Включить" }).click();
    await expect(section.locator("canvas, svg").first()).toBeVisible();
    await waitForMotionEnd(page);
    if (dir)
      await page.screenshot({
        path: `${dir}/profile-2fa-setup-${String(width)}.png`,
        fullPage: true,
      });
    await expectNoViolations(page, "настройка второго фактора");

    await section.getByLabel("Код из приложения").fill("000000");
    await section.getByRole("button", { name: "Подтвердить" }).click();
    await expect(section.getByText(/Неверный код/)).toBeVisible();
    await section.getByLabel("Код из приложения").fill("123456");
    await section.getByRole("button", { name: "Подтвердить" }).click();
    await expect(section.getByRole("list", { name: /Сохраните резервные коды/ })).toBeVisible();
    await waitForMotionEnd(page);
    if (dir)
      await page.screenshot({
        path: `${dir}/profile-2fa-backup-${String(width)}.png`,
        fullPage: true,
      });
    await section.getByRole("button", { name: "Я сохранил коды" }).click();
    await expect(section.getByText(/Включён с/)).toBeVisible();

    await page.evaluate("window.localStorage.removeItem('rt-pf-mock-session')");
    await page.goto("/login");
    await page.getByLabel("Электронная почта").fill("admin@demo.example");
    await page.getByLabel("Пароль").fill("demo-password");
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Код из приложения" })).toBeVisible();
    await waitForMotionEnd(page);
    if (dir)
      await page.screenshot({ path: `${dir}/login-2fa-${String(width)}.png`, fullPage: true });
    await expectNoViolations(page, "вход: код");
    await page.getByLabel("Код", { exact: true }).fill("111111");
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page.getByRole("alert")).toContainText("Неверный код");
    await page.getByLabel("Код", { exact: true }).fill("123456");
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page).toHaveURL(/\/dashboard\/queue$/);

    // устройство запомнено: следующий вход — без кода
    await page.evaluate("window.localStorage.removeItem('rt-pf-mock-session')");
    await page.goto("/login");
    await page.getByLabel("Электронная почта").fill("admin@demo.example");
    await page.getByLabel("Пароль").fill("demo-password");
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page).toHaveURL(/\/dashboard\/queue$/);
  });
}
