import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// КАРКАС-3: экраны объектов в `PageFrame` (раскладка `object`). Снимки: `E2E_SCREENSHOT_DIR=docs/screens/frame3/<before|after>`.
const WIDTHS = [1512, 390] as const;
const PAGES = [
  ["letter", "/eds/inbox/%D0%92%D0%A5-104%2F26"],
  ["quote", "/eds/drafts/40000000-0000-4000-8000-000000001150"],
  ["order-new", "/erp/stock/new"],
  ["new-letter", "/eds/new?type=letter"],
] as const;

for (const width of WIDTHS) {
  test(`экраны объектов в каркасе на ${String(width)} px`, async ({ page }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width, height: 900 });
    await loginAndWait(page, "admin@demo.example");
    for (const [key, path] of PAGES) {
      await spaGoto(page, path);
      await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
      const overflow = await page.evaluate<number>(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth",
      );
      expect(overflow, `${path}: прокрутка вбок`).toBeLessThanOrEqual(0);
      await expectNoViolations(page, `${path} ${String(width)}`);
      await page.mouse.move(0, 0);
      await settledScreenshot(page, key);
    }
  });
}
