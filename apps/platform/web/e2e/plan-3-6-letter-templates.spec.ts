import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";

// План 3.6 (TPL-4) на MSW: «Настройки · Шаблоны · Письма на бланке» — шаблон с вариантами по языкам и PDF на бланке.
// Снимки 1440 и 390 с axe — E2E_SCREENSHOT_DIR (docs/screens/plan-3-6).
test("шаблон письма: варианты по языкам и PDF на бланке", async ({ page }) => {
  test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
  await loginAndWait(page, "director@demo.example");
  await spaGoto(page, "/admin/templates?tab=letters");
  await page.getByRole("button", { name: "Открыть: Деловое письмо" }).click();
  const dialog = page.getByRole("dialog", { name: "Деловое письмо" });
  await dialog.getByText("UZ", { exact: true }).click();
  await expect(dialog.getByRole("textbox", { name: "Текст (UZ)" })).toContainText(
    "Hurmatli hamkasblar!",
  );
  await expect(dialog.locator("canvas").first()).toBeVisible({ timeout: 15_000 });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
    await waitForMotionEnd(page);
    const dir = process.env["E2E_SCREENSHOT_DIR"];
    if (dir) {
      await page.waitForTimeout(400);
      await page.screenshot({ path: `${dir}/letter-template-${String(width)}.png` });
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
