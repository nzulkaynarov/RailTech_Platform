import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// X-16: поиск МХИК по слову («накладка» — рельсовые и вагонные позиции, под каждой путь по группам), публикация без МХИК
// закрыта словами и ведёт к полю, обязательные коды — переключатели в «Продажи». Снимки — docs/screens/x16-mxik-search.
const WIDTHS = [1440, 390] as const;

for (const width of WIDTHS) {
  test(`карточка без МХИК: причина, переход к полю, поиск «накладка» (${String(width)})`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/erp/catalog?item=5");
    const drawer = page.getByRole("dialog", { name: "Пусконаладочные работы" });
    await expect(drawer.getByText(/Для публикации заполните:.*код МХИК \(ИКПУ\)/)).toBeVisible();
    await expect(drawer.getByRole("button", { name: "Опубликовать" })).toBeDisabled();
    await drawer.getByRole("button", { name: "Указать МХИК" }).scrollIntoViewIfNeeded();
    await expectNoViolations(page, "карточка без МХИК: причина публикации");
    await settledScreenshot(page, "publish-reason");

    await drawer.getByRole("button", { name: "Указать МХИК" }).click();
    const field = page.getByLabel("МХИК (ИКПУ)");
    await expect(field).toBeFocused();
    await field.fill("накладка");
    const hit = page.getByText("Изделия из чёрных металлов › Детали железнодорожного пути");
    await expect(hit).toBeVisible();
    await expect(page.getByText(/Накладки тормозные для вагонов/)).toBeVisible();
    await expect(page.getByText(/пассажиров|газоснабжение/i)).toHaveCount(0);
    await settledScreenshot(page, "search-results");
  });

  test(`«Продажи»: обязательные коды для публикации (${String(width)})`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/admin/sales");
    const mxik = page.getByRole("switch", { name: "МХИК обязателен для публикации" });
    await mxik.scrollIntoViewIfNeeded();
    await expect(mxik).toBeChecked();
    await expect(
      page.getByRole("switch", { name: "ТН ВЭД обязателен для ввозимого товара" }),
    ).toBeChecked();
    await expectNoViolations(page, "Продажи: обязательные коды");
    await settledScreenshot(page, "sales-required-codes");
  });
}
