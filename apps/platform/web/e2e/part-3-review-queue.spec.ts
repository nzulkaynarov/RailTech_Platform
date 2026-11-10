import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, partnerCard } from "./support/app";
import { expectNoViolations } from "./support/axe";
import { chooseOption } from "./support/fields";

// PART-3: очередь проверки карточек партнёров на MSW. Снабженец видит «Ждут проверки» со сроками, возвращает карточку с
// причинами по полям, публикует полную карточку, решает правку партнёра к опубликованной; цены партнёра — в «Доступ в кабинет».
// Снимки 1440 и 390 px и axe (WCAG 2.1 AA).

const WIDTHS = [1440, 390] as const;

for (const width of WIDTHS) {
  test(`очередь проверки партнёров, ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/erp/catalog?review=waiting");

    // Очередь: старые сверху, срок и полнота; счётчик на переключателе
    const list = page.getByRole(width === 390 ? "list" : "table", {
      name: "Очередь проверки партнёров",
    });
    await expect(page.getByText("Ждут проверки · 3")).toBeVisible();
    await expect(list.getByText("Просрочено").first()).toBeVisible();
    await expect(list.getByText("В срок")).toBeVisible();
    await expectNoViolations(page, "Номенклатура · очередь проверки");
    await settledScreenshot(page, "review-queue");

    // Возврат с причинами по полям
    await spaGoto(page, "/erp/catalog?review=waiting&item=6");
    const drawer = page.getByRole("dialog", { name: "Болт М20×80 оцинкованный" });
    await expect(drawer.getByText("Проверка карточки")).toBeVisible();
    await expect(drawer.getByText("Цена в каталоге")).toBeVisible();
    await expect(drawer.getByRole("button", { name: "Опубликовать" })).toBeDisabled();
    await expect(drawer.getByText(/Для публикации заполните: код ТН ВЭД/)).toBeVisible();
    await expectNoViolations(page, "Номенклатура · карточка на проверке");
    await settledScreenshot(page, "review-card");

    await drawer.getByRole("button", { name: "Вернуть партнёру" }).click();
    const form = page.getByRole("dialog", { name: "Вернуть карточку партнёру" });
    await expect(form.getByRole("button", { name: "Вернуть", exact: true })).toBeDisabled();
    await form.getByRole("button", { name: "Добавить замечание" }).click();
    await chooseOption(form.getByRole("combobox", { name: "Поле 1" }), "Артикул изготовителя");
    await form.getByRole("textbox", { name: "Замечание 1" }).fill("Укажите артикул по шильдику");
    await form.getByLabel("Общий комментарий").fill("Не хватает данных для каталога");
    await expectNoViolations(page, "Номенклатура · возврат партнёру");
    await settledScreenshot(page, "review-return");
    await form.getByRole("button", { name: "Вернуть", exact: true }).click();
    await expect(form).toBeHidden();
    await expect(page.getByText("Ждут проверки · 2")).toBeVisible();

    // Публикация полной карточки
    await spaGoto(page, "/erp/catalog?review=waiting&item=7");
    const complete = page.getByRole("dialog", { name: "Шайба пружинная 20" });
    await complete.getByRole("button", { name: "Опубликовать" }).click();
    await expect(page.getByText("Ждут проверки · 1")).toBeVisible();
  });

  test(`цены партнёра в каталоге, ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/erp/catalog?part=suppliers&supplier=2");
    const drawer = partnerCard(page, "АО «Южный Металл»");
    const block = drawer.getByRole("region", { name: "Доступ в кабинет" });
    const select = block.getByRole("combobox", { name: "Цены товаров в каталоге" });
    await chooseOption(select, "Показывать");
    await expect(
      block.locator(".ant-select-selection-item", { hasText: "Показывать" }),
    ).toBeVisible();
    await block.scrollIntoViewIfNeeded();
    await expectNoViolations(page, "Партнёр · цены партнёра в каталоге");
    await settledScreenshot(page, "partner-price");

    // В карточке товара партнёра каталог покажет цену-витрину
    await spaGoto(page, "/erp/catalog?item=7");
    const card = page.getByRole("dialog", { name: "Шайба пружинная 20" });
    await expect(card.getByText("по договорённости с партнёром")).toBeVisible();
  });
}
