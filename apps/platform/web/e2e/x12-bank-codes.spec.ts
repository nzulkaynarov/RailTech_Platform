import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, waitForMotionEnd } from "./support/app";

// Х-12: справочник «Банки» с источником «ЦБ» — строка источника, «Обновить», «Вручную» и отметка пропавшего кода с датой.
// axe 0 и снимки 1440 и 390 (`E2E_SCREENSHOT_DIR` → docs/screens/x12-bank-codes/).
const WIDTHS = [1440, 390] as const;

async function expectNoViolations(page: Page, context: string): Promise<void> {
  await waitForMotionEnd(page);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`),
    context,
  ).toEqual([]);
}

test.describe("Х-12 · справочник банков из файла ЦБ", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("источник с датой, «Вручную» и пропавший код с датой последнего файла", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    await page.goto("/admin/dictionaries?list=banks");
    await expect(page.getByText(/^Источник: ЦБ · /)).toBeVisible();
    await expect(page.getByRole("row", { name: /00014/ })).toContainText("ЦБ · ");
    await expect(page.getByRole("row", { name: /99001/ })).toContainText("Вручную");
    // Код, которого нет в последнем файле: не удалён, отмечен с датой последнего файла, где он был.
    const gone = page.getByRole("row", { name: /00401/ });
    await expect(gone).toContainText("Нет в источнике");
    await expect(gone).toContainText(/последний раз в файле \d{2}\.\d{2}\.\d{4}/);
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await expectNoViolations(page, `banks ${String(width)}`);
      if (width === 390) {
        const overflow = await page.evaluate<number>(
          "document.documentElement.scrollWidth - document.documentElement.clientWidth",
        );
        expect(overflow).toBeLessThanOrEqual(0);
      }
      await settledScreenshot(page, "banks-source");
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.getByRole("button", { name: "Обновить" }).click();
    await expect(page.getByText(/Обновление запущено/)).toBeVisible();
  });
});
