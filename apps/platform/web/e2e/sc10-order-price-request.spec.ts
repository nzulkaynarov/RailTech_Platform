import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// СЦ-10: в черновике без цены — «Запросить цену»: строки без цены уходят партнёру, карточка показывает, что запрос
// отправлен; ответ партнёра из кабинета впишет цены в черновик. Снимки 1440 и 390 и axe — docs/screens/sc10-order-price-request.
const NEW_ORDER = `ЗП-${String(new Date().getFullYear())}-030`;
const WIDTHS = [1440, 390] as const;

for (const width of WIDTHS) {
  test(`запрос цены из черновика заказа (${String(width)})`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/erp/stock?view=orders");
    await page.getByRole("link", { name: "Создать заказ" }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: "Новый заказ партнёру" }),
    ).toBeVisible();
    const create = page.getByRole("main");
    await create.getByRole("combobox", { name: "Партнёр" }).click();
    await page.locator(".ant-select-dropdown").getByTitle("ООО «Вымышленная Сталь»").click();
    await create.getByRole("button", { name: /^Строки/, expanded: false }).click();
    const product = create.getByRole("combobox", { name: "Товар, строка 1" });
    await product.click();
    await product.pressSequentially("перевод");
    await page.getByTitle(/Перевод стрелочный Р65 марки 1\/11/).click();
    await create.getByRole("spinbutton", { name: "Количество, строка 1" }).fill("4");
    await create.getByRole("button", { name: "Создать черновик" }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: `Заказ партнёру ${NEW_ORDER}` }),
    ).toBeVisible();

    await page.getByRole("button", { name: "Запросить цену" }).click();
    const dialog = page.getByRole("dialog", { name: `Запросить цену · ${NEW_ORDER}` });
    await expect(dialog.getByText("Партнёр получит запрос по 1 строке без цены.")).toBeVisible();
    await expectNoViolations(page, "окно «Запросить цену»");
    await settledScreenshot(page, "price-request-dialog");

    await dialog.getByRole("button", { name: "Отправить запрос" }).click();
    await expect(page.getByText(/Запрос цены отправлен .* — ждём ответа\./)).toBeVisible();
    await expectNoViolations(page, "черновик после запроса цены");
    await settledScreenshot(page, "order-after-price-request");
  });
}
