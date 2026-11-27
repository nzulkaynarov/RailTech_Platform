import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// КАРКАС-2: остальные страницы Настроек и реестры CRM/EDS в `PageFrame`. Снимки: `E2E_SCREENSHOT_DIR=docs/screens/frame2/<before|after>`.
const WIDTHS = [1512, 390] as const;
const PAGES = [
  ["org", "/admin/org?view=list"],
  ["roles", "/admin/roles"],
  ["audit", "/admin/audit"],
  ["integrations", "/admin/integrations"],
  ["leads", "/crm/leads"],
  ["documents", "/eds/documents"],
] as const;

for (const width of WIDTHS) {
  test(`страницы в каркасе на ${String(width)} px`, async ({ page }) => {
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
