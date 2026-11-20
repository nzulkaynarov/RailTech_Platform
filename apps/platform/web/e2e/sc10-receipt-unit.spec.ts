import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// СЦ-10: при приёмке видно, в чём количество — «осталось 30 из 30 компл.», журнал и приёмки в единице строки заказа.
// Снимки 1440 и 390 и axe — docs/screens/sc10-receipt-unit.
const ORDER = `ЗП-${String(new Date().getFullYear())}-029`;
const WIDTHS = [1440, 390] as const;

for (const width of WIDTHS) {
  test(`приёмка в единице строки заказа (${String(width)})`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, `/erp/stock/${encodeURIComponent(ORDER)}`);
    await expect(page.getByRole("heading", { level: 1 })).toContainText(ORDER);

    await page.getByRole("button", { name: "Принять товар" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText(/осталось \d+ из \d+ компл\./).first()).toBeVisible();
    await expectNoViolations(page, "окно приёмки с единицей");
    await settledScreenshot(page, "receive-dialog");

    await dialog.getByRole("button", { name: "Принять" }).click();
    await expect(page.getByText("Товар принят")).toBeVisible();
    await expect(page.getByText(/компл\. · накладная|^\d+\sкомпл\.$/).first()).toBeVisible();
    await expectNoViolations(page, "карточка заказа после приёмки");
    await settledScreenshot(page, "order-after-receipt");
  });
}
