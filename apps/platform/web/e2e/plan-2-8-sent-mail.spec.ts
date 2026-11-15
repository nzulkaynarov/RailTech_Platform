import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";

// План 2.8 (MAIL-1) на MSW: «Почта · Отправленные» — журнал писем с поиском и текстом по нажатию.
// Снимки 1440 и 390 с axe — E2E_SCREENSHOT_DIR (docs/screens/plan-2-8).
test("отправленные письма: список и текст письма", async ({ page }) => {
  test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
  await loginAndWait(page, "registrar@demo.example");
  await spaGoto(page, "/eds/mail?tab=sent");
  await expect(page.getByRole("table", { name: "Отправленные письма" })).toBeVisible();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
    await waitForMotionEnd(page);
    const dir = process.env["E2E_SCREENSHOT_DIR"];
    if (dir) {
      await page.waitForTimeout(400);
      await page.screenshot({ path: `${dir}/sent-${String(width)}.png`, fullPage: true });
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
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: /Ответ на требование о пояснениях/ }).click();
  const drawer = page.getByRole("dialog", { name: /Ответ на требование/ });
  await expect(drawer.getByText(/Направляем ответ на требование/)).toBeVisible();
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (dir) await page.screenshot({ path: `${dir}/sent-text-1440.png` });
});
