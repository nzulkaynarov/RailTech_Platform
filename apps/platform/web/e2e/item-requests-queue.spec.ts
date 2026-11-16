import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ADR-0027: каталог · «Новые из заявок» на MSW. Снабженец видит черновики из строк расчёта (самые спрашиваемые сверху,
// номера заявок, похожая карточка) и сливает дубль с опубликованной позицией. Снимки 1440 и 390 px и axe (WCAG 2.1 AA).

const WIDTHS = [1440, 390] as const;

for (const width of WIDTHS) {
  test(`новые из заявок, ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/erp/catalog?review=requests");

    const list = page.getByRole(width === 390 ? "list" : "table", {
      name: "Новые позиции из заявок",
    });
    await expect(page.getByText("Новые из заявок · 2")).toBeVisible();
    await expect(list.getByText(/Похожа на «Реле защиты РЗ-1»/)).toBeVisible();
    await expectNoViolations(page, "Каталог · новые из заявок");
    await settledScreenshot(page, "item-requests-queue");

    await list.getByRole("button", { name: "Слить с RT-0002: «реле защиты рз-1»" }).click();
    const dialog = page.getByRole("dialog", { name: "Слить «реле защиты рз-1»?" });
    await expect(dialog).toBeVisible();
    await expectNoViolations(page, "Каталог · подтверждение слияния");
    await settledScreenshot(page, "item-requests-merge");
    await dialog.getByRole("button", { name: "Слить" }).click();
    await expect(page.getByText("Карточки слиты")).toBeVisible();
    await expect(list.getByText("реле защиты рз-1")).toHaveCount(0);
  });
}
