import { appendFileSync } from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, screenshot, spaGoto, waitForMotionEnd } from "./support/app";
import { pickRowAction } from "./support/rowActions";

// ДОК-14: образец в «Реквизитах и бланке» и в «Шаблонах» — PDF настоящего генератора в общем просмотрщике.
// Снимки 1512 и 390 с axe — E2E_SCREENSHOT_DIR (docs/screens/dok14-real-sample).
const WIDTHS = [1512, 390] as const;

async function expectNoViolations(page: Page, context: string): Promise<void> {
  await waitForMotionEnd(page);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (dir) {
    appendFileSync(
      `${dir}/axe-results.txt`,
      `${context}: axe violations=${String(results.violations.length)}\n`,
    );
  }
  expect(
    results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`),
    context,
  ).toEqual([]);
}

for (const width of WIDTHS) {
  test.describe(`образец — настоящий PDF, ${String(width)}`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 960 });
      await loginAndWait(page, "director@demo.example");
    });

    test("реквизиты и бланк: PDF образца КП, язык, несохранённая правка", async ({ page }) => {
      await spaGoto(page, "/admin/company?tab=brand");
      const pages = page.getByRole("img", { name: /Образец: КП/ });
      await expect(pages.first()).toBeVisible();
      await page.getByLabel("Основной цвет", { exact: true }).fill("#047857");
      await page.locator(".ant-segmented-item-label", { hasText: "EN" }).click();
      await page.locator(".ant-segmented-item-label", { hasText: "Договор" }).click();
      await expect(page.getByRole("img", { name: /Образец: Договор/ }).first()).toBeVisible();
      await page
        .getByRole("img", { name: /Образец: Договор/ })
        .first()
        .scrollIntoViewIfNeeded();
      await page.waitForTimeout(500);
      await screenshot(page, "brand-sample-pdf");
      await expectNoViolations(page, `brand sample ${String(width)}`);
    });

    test("шаблоны: PDF образца по тексту редактора", async ({ page }) => {
      await spaGoto(page, "/admin/company?tab=templates");
      await pickRowAction(page, "Акт приёмки", "Изменить");
      const editor = page.getByRole("region", { name: "Изменить шаблон документа" });
      await expect(
        editor.getByRole("img", { name: /Образец документа по шаблону/ }).first(),
      ).toBeVisible();
      await editor
        .getByRole("img", { name: /Образец документа по шаблону/ })
        .first()
        .scrollIntoViewIfNeeded();
      await page.waitForTimeout(500);
      await screenshot(page, "templates-sample-pdf");
      await expectNoViolations(page, `templates sample ${String(width)}`);
    });
  });
}
