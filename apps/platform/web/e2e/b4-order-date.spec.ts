import { expect, test } from "@playwright/test";

import { chooseOrAddAddressee } from "./support/fields";
import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// Б-4: «Отмена» нового заказа ведёт к заказам; черновик с ценой, но без даты, главной кнопкой предлагает «Указать дату».
// Снимки 1512, 1440 и 390 и axe — docs/screens/b4.
const NEW_ORDER = `ЗП-${String(new Date().getFullYear())}-030`;
const WIDTHS = [1512, 1440, 390] as const;

for (const width of WIDTHS) {
  test(`заказ партнёру: отмена и «Указать дату» (${String(width)})`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/erp/stock?view=orders");
    await page.getByRole("link", { name: "Создать заказ" }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: "Новый заказ партнёру" }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Отмена" })).toHaveAttribute(
      "href",
      "/erp/stock?view=orders",
    );
    const create = page.getByRole("main");
    await chooseOrAddAddressee(page, "ООО «Вымышленная Сталь»", "Партнёр");
    await create.getByRole("button", { name: /^Строки/, expanded: false }).click();
    await expect(create.getByText(/Без даты и цен заказ партнёру не уйдёт/)).toBeVisible();
    await settledScreenshot(page, "order-create-hint");
    await expectNoViolations(page, "новый заказ с подсказкой про дату");
    const product = create.getByRole("combobox", { name: "Товар, строка 1" });
    await product.click();
    await product.pressSequentially("перевод");
    await page.getByTitle(/Перевод стрелочный Р65 марки 1\/11/).click();
    await create.getByRole("spinbutton", { name: "Количество, строка 1" }).fill("4");
    await create
      .getByRole("textbox", { name: "Цена партнёра за единицу, строка 1" })
      .fill("185000");
    await create.getByRole("button", { name: "Создать черновик" }).click();

    await expect(
      page.getByRole("heading", { level: 1, name: `Заказ партнёру ${NEW_ORDER}` }),
    ).toBeVisible();
    await expect(page.getByText("Нет ожидаемой даты")).toBeVisible();
    await expect(page.getByRole("button", { name: "Указать дату" })).toBeVisible();
    await expectNoViolations(page, "черновик без даты");
    await settledScreenshot(page, "order-set-date");
  });
}
