import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// КАРКАС-1: один каркас страницы — содержимое на всю доступную ширину, карточки в 1–3 колонки по ширине страницы.
// Снимки: `E2E_SCREENSHOT_DIR=docs/screens/frame1`; первым идёт 1512.
const WIDTHS = [1512, 1920, 1440, 390] as const;
const PAGES = [
  ["state", "/admin", "Состояние"],
  ["numbering", "/admin/numbering", "Нумерация"],
  ["company", "/admin/company", "Реквизиты и бланк"],
  ["sales", "/admin/sales", "Продажи"],
  ["org", "/admin/org?view=list", "Сотрудники и возможности"],
] as const;

for (const width of WIDTHS) {
  test(`каркас страницы на ${String(width)} px: ширина, без прокрутки вбок, axe`, async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width, height: 900 });
    await loginAndWait(page, "admin@demo.example");
    for (const [key, path, title] of PAGES) {
      await spaGoto(page, path);
      await expect(page.getByRole("heading", { level: 1, name: title, exact: true })).toBeVisible();
      const overflow = await page.evaluate<number>(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth",
      );
      expect(overflow, `${path}: прокрутка вбок`).toBeLessThanOrEqual(0);
      const frame = page.locator(".pf-frame").first();
      if (key !== "state" && key !== "org") {
        const box = await frame.boundingBox();
        const main = await page.locator("#main-content").boundingBox();
        // Каркас не уже содержимого окна больше чем на поля: никаких 560 / 768 px.
        expect(box?.width ?? 0, `${path}: ширина каркаса`).toBeGreaterThan(
          Math.min(width - 520, 900),
        );
        expect(main).not.toBeNull();
      }
      await expectNoViolations(page, `${path} ${String(width)}`);
      await page.mouse.move(0, 0);
      await page.evaluate("document.getElementById('main-content')?.scrollTo(0, 0)");
      await settledScreenshot(page, `${key}-${String(width)}`);
    }
  });
}
