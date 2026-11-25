import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";
import { chooseOrAddAddressee, fillDate } from "./support/fields";

// Б-5: письмо партнёру отправленного заказа не ушло — главная кнопка «Отправить ещё раз», письмо уходит снова.
// Снимки 1512, 1440 и 390 и axe — docs/screens/b5.
const ORDER = `ЗП-${String(new Date().getFullYear())}-030`;

for (const width of [1512, 1440, 390] as const) {
  test(`заказ с письмом, которое не ушло: «Отправить ещё раз» (${String(width)})`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/erp/stock?view=orders");
    await page.getByRole("link", { name: "Создать заказ" }).click();
    const create = page.getByRole("main");
    await chooseOrAddAddressee(page, "ООО «Вымышленная Сталь»", "Партнёр");
    await create.getByRole("button", { name: /^Строки/, expanded: false }).click();
    const product = create.getByRole("combobox", { name: "Товар, строка 1" });
    await product.click();
    await product.pressSequentially("перевод");
    await page.getByTitle(/Перевод стрелочный Р65 марки 1\/11/).click();
    await create.getByRole("spinbutton", { name: "Количество, строка 1" }).fill("4");
    await create.getByRole("textbox", { name: "Цена партнёра за единицу, строка 1" }).fill("250");
    await fillDate(create.getByLabel("Ожидаемая дата"), "2099-01-10");
    await create.getByRole("button", { name: "Создать черновик" }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: `Заказ партнёру ${ORDER}` }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Отправить партнёру" }).click();
    const first = page.getByRole("dialog", { name: `Отправить заказ ${ORDER} партнёру` });
    await first.getByRole("button", { name: "Отправить письмо" }).click();
    await expect(
      page.getByText(/^Заказ оформлен\. Письмо партнёру — в очереди почты/),
    ).toBeVisible();
    // почтовый сервис вернул отказ: «Письмо партнёру: не отправлено»
    await page.evaluate(
      `(() => {
        const key = "rt-pf-mock-stock-v1";
        const state = JSON.parse(window.localStorage.getItem(key) ?? "{}");
        const order = state.orders.find((o) => o.number === ${JSON.stringify(ORDER)});
        if (order) order.mail = { state: "failed", reason: "smtp_not_configured" };
        window.localStorage.setItem(key, JSON.stringify(state));
      })()`,
    );

    await page.reload();
    await expect(
      page.getByRole("heading", { level: 1, name: `Заказ партнёру ${ORDER}` }),
    ).toBeVisible();
    const again = page.getByRole("button", { name: "Отправить ещё раз" });
    await expect(again).toBeVisible();
    await settledScreenshot(page, "order-resend");
    await expectNoViolations(page, `заказ, письмо не ушло, ${String(width)}`);

    await again.click();
    const dialog = page.getByRole("dialog", { name: `Отправить заказ ${ORDER} партнёру` });
    await dialog.getByRole("button", { name: "Отправить письмо" }).click();
    await expect(again).toBeHidden();
    await expect(page.getByRole("button", { name: "Партнёр подтвердил" })).toBeVisible();
  });
}
