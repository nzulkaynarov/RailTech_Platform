import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";

// План 2.7 (TPL-1) на MSW: «Настройки · Шаблоны · Все шаблоны» — шаблоны всех разделов одной таблицей.
// Снимки 1440 и 390 с axe — E2E_SCREENSHOT_DIR (docs/screens/plan-2-7).
test("все шаблоны одной таблицей", async ({ page }) => {
  test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
  await loginAndWait(page, "director@demo.example");
  await spaGoto(page, "/admin/templates");
  const table = page.getByRole("table", { name: "Шаблоны всех разделов" });
  await expect(table.getByRole("link", { name: "Коммерческое предложение" }).first()).toBeVisible();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
    await waitForMotionEnd(page);
    const dir = process.env["E2E_SCREENSHOT_DIR"];
    if (dir) {
      await page.waitForTimeout(400);
      await page.screenshot({ path: `${dir}/all-templates-${String(width)}.png`, fullPage: true });
    }
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(
      results.violations.map(
        (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`,
      ),
      String(width),
    ).toEqual([]);
  }
});
