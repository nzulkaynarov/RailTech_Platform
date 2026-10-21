import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// Каркас P0: страница-заглушка читает getHealth у MSW (моки orval) и проходит axe (WCAG 2.1 AA).
// `E2E_SCREENSHOT_DIR=<каталог>` сохраняет скриншот (артефакт PR, ORCHESTRATOR §7 п. 5).
test("страница-заглушка показывает состояние сервисов и проходит axe", async ({ page }) => {
  await page.goto("/");

  await expect(
    page.getByRole("heading", { level: 1, name: "Платформа — каркас P0" }),
  ).toBeVisible();
  await expect(page.getByTestId("health-status")).toHaveText("Работает");
  for (const source of ["Redis (сессии)", "CRM", "ERP"]) {
    await expect(page.getByText(source, { exact: true })).toBeVisible();
  }
  await expect(page.getByText("Версия BFF")).toBeVisible();

  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(results.violations).toEqual([]);

  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (dir) {
    const width = page.viewportSize()?.width ?? 0;
    await page.screenshot({ path: `${dir}/scaffold-${String(width)}.png`, fullPage: true });
  }
});
