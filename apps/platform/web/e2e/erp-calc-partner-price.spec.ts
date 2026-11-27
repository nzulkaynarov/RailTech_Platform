import { type Page, expect, test } from "@playwright/test";

import { expectNoViolations } from "./support/axe";
import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";

// РАСЧ-1 на MSW: закупка строки подписана «цена партнёра … от … действует до …»; другую цену выбирают из короткого списка,
// после чего закупка и валюта строки меняются; снимки 1440 и 390, axe без нарушений.
const NUMBER = "ЗВ-2026-097";
// Телефон первым: на 1440 сценарий меняет выбранную цену.
const WIDTHS = [390, 1440] as const;

/** Таблица шире окна и прокручивается внутри: для снимка двигаем её к колонке закупки. */
async function showPurchaseColumn(page: Page): Promise<void> {
  await page.getByTestId("partner-source").first().scrollIntoViewIfNeeded();
  await page.evaluate(
    `document.querySelectorAll(".pf-fp-scroll").forEach((region) => { region.scrollLeft = region.scrollWidth; })`,
  );
}

test("закупка берёт цену партнёра, другую цену выбирают из списка", async ({ page }) => {
  await loginAndWait(page, "supply@demo.example");
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await spaGoto(page, `/erp/calc/${encodeURIComponent(NUMBER)}`);
    await expect(
      page.getByRole("heading", { level: 1, name: `Расчёт по заявке ${NUMBER}` }),
    ).toBeVisible();

    const source = page.getByTestId("partner-source").first();
    await expect(source).toContainText("Цена партнёра ООО «Вымышленная Сталь»");
    await expect(source).toContainText("действует до");
    await showPurchaseColumn(page);
    await settledScreenshot(page, `partner-price-${String(width)}`);
    await expectNoViolations(page, `расчёт с ценой партнёра, ${String(width)} px`);

    if (width === 1440) {
      await page.locator(".pf-calc-partner-pick").first().click();
      await page.getByText(/ООО «Демо Металл» · /).click();
      await expect(page.getByTestId("partner-source").first()).toContainText(
        "Цена партнёра ООО «Демо Металл»",
      );
      await showPurchaseColumn(page);
      await settledScreenshot(page, "partner-price-picked-1440");
    }
  }
});
