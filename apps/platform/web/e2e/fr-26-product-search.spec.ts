import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { loginAndWait, waitForMotionEnd } from "./support/app";

// FR-26 на MSW: поиск ⌘K находит товар каталога по названию, набранному латиницей, и открывает его карточку.
// Снимки 1440 и 390 с axe — E2E_SCREENSHOT_DIR (docs/screens/fr-26).
test("товар по названию латиницей в поиске ⌘K", async ({ page }) => {
  test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
  await loginAndWait(page, "director@demo.example");
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
    const search = page.getByRole("combobox", { name: "Глобальный поиск" });
    if (!(await search.isVisible())) await page.getByRole("button", { name: "Поиск" }).click();
    await search.fill("kabel silovoy");
    const option = page.getByRole("option", { name: /Кабель силовой ВВГнг/ });
    await expect(option).toBeVisible();
    await waitForMotionEnd(page);
    const dir = process.env["E2E_SCREENSHOT_DIR"];
    if (dir) await page.screenshot({ path: `${dir}/search-product-${String(width)}.png` });
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(
      results.violations.map((v) => v.id),
      String(width),
    ).toEqual([]);
    if (width === 1440) {
      await option.click();
      await expect(page).toHaveURL(/\/erp\/catalog\?item=/);
    } else {
      await page.keyboard.press("Escape");
    }
  }
});
