import { expect, test } from "@playwright/test";

import { chooseOrAddAddressee } from "./support/fields";
import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// СЦ-10: заказ партнёру без цены и ожидаемой даты не уходит — карточка черновика говорит, чего не хватает, а «Изменить»
// даёт ввести цену по строкам. Снимки 1440 и 390 и axe — docs/screens/sc10-order-incomplete.
const NEW_ORDER = `ЗП-${String(new Date().getFullYear())}-030`;
const WIDTHS = [1440, 390] as const;

for (const width of WIDTHS) {
  test(`черновик без цены и даты (${String(width)})`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/erp/stock?view=orders");
    await page.getByRole("link", { name: "Создать заказ" }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: "Новый заказ партнёру" }),
    ).toBeVisible();
    const create = page.getByRole("main");
    await chooseOrAddAddressee(page, "ООО «Вымышленная Сталь»", "Партнёр");
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
    await expect(page.getByText("Без цены: 1 строка · Нет ожидаемой даты")).toBeVisible();
    await expect(page.getByRole("button", { name: "Отправить партнёру" })).toHaveCount(0);
    await expectNoViolations(page, "черновик без цены и даты");
    await settledScreenshot(page, "order-incomplete");

    await page.getByRole("button", { name: "Изменить" }).click();
    const edit = page.getByRole("dialog");
    await expect(edit.getByRole("textbox", { name: /^Цена, «Перевод стрелочный/ })).toBeVisible();
    await expectNoViolations(page, "«Изменить» с ценой строки");
    await settledScreenshot(page, "order-edit-price");
  });
}
