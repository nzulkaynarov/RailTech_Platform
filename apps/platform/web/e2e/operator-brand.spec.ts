import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ДВ-3 на MSW: логотип своей компании из «Настройки · Компания» — в рейле и на экране входа; без логотипа — буквы.
// Снимки 1440 и 390 с axe — E2E_SCREENSHOT_DIR (docs/screens/operator-brand).
const SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96"><rect width="96" height="96" rx="12" fill="#1e3a5f"/><path d="M24 64 L48 28 L72 64 Z" fill="#fff"/></svg>';
const dir = process.env["E2E_SCREENSHOT_DIR"];

for (const width of [1440, 390] as const) {
  test(
    `логотип оператора в рейле и на входе, ${String(width)}`,
    { tag: "@mobile" },
    async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin/company");
      await page
        .getByLabel(/Выбрать файл/)
        .first()
        .setInputFiles({ name: "logo.svg", mimeType: "image/svg+xml", buffer: Buffer.from(SVG) });
      await expect(page.getByText("Логотип загружен").first()).toBeVisible();

      if (width === 1440) {
        await page.reload();
        const rail = page.getByRole("navigation", { name: "Модули" });
        await expect(rail.locator("img").first()).toHaveAttribute("src", /^blob:/);
        await waitForMotionEnd(page);
        if (dir) await page.screenshot({ path: `${dir}/rail-logo-1440.png` });
      }

      await page.evaluate("window.localStorage.removeItem('rt-pf-mock-session')");
      await page.goto("/login");
      await expect(page.locator("main img").first()).toHaveAttribute("src", /^blob:/);
      await expect(
        page.getByText("Мы не просим пароль и код в письме или по телефону."),
      ).toBeVisible();
      await waitForMotionEnd(page);
      if (dir)
        await page.screenshot({ path: `${dir}/login-logo-${String(width)}.png`, fullPage: true });
      await expectNoViolations(page, "вход с логотипом");
    },
  );
}
