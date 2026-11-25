import { expect, test } from "@playwright/test";

import { chooseOrAddAddressee } from "./support/fields";
import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// В-2 (аудит конфиденциальности 2026-11-25): в запрос цены партнёру уходит название нашей карточки; слова клиента — только
// после того, как сотрудник назвал строку («как назвать партнёру»), а комментарий виден в предпросмотре до отправки.
// Снимки 1512, 1440 и 390 и axe — docs/screens/leak3.
const NUMBER = "ЗВ-2026-097";
const CLIENT_WORDS = "Стрелка для ст. Чиланзар, ООО МетроСтрой";
const WIDTHS = [1512, 1440, 390] as const;

for (const width of WIDTHS) {
  test(`запрос цены: предпросмотр и название для партнёра (${String(width)})`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, `/erp/calc/${encodeURIComponent(NUMBER)}`);
    await expect(
      page.getByRole("heading", { level: 1, name: `Расчёт по заявке ${NUMBER}` }),
    ).toBeVisible();

    // строка клиента без карточки каталога: слова заявки с названием объекта и компании
    await page.getByRole("button", { name: "Добавить строку" }).click();
    const form = page.getByRole("region", { name: "Новая строка расчёта" });
    await form.getByLabel("Наименование").fill(CLIENT_WORDS);
    await form.getByRole("button", { name: "Добавить" }).click();
    await expect(form).toBeHidden();

    // после добавления строки в боковом окне — задача расчёта; форму запроса открываем поверх экрана
    const hide = page.getByRole("button", { name: "Скрыть боковое окно" });
    if (await hide.isVisible()) await hide.click();
    await page.getByRole("button", { name: "Запросить цену у партнёра" }).click();
    const request = page.getByRole("region", { name: `Запросить цену у партнёра · ${NUMBER}` });
    await chooseOrAddAddressee(page, "ООО «Вымышленная Сталь»", "Партнёр");
    await request.getByLabel("Комментарий партнёру").fill("Нужны сертификаты");
    const preview = request.getByRole("region", { name: "Что увидит партнёр" });
    await expect(preview.getByText(/Нужны сертификаты/)).toBeVisible();
    // слова клиента — только сотруднику и только как подсказка; поле пустое, отправить нельзя
    const field = preview.getByLabel(/^Как назвать партнёру/).last();
    await expect(field).toHaveValue("");
    await expect(preview.getByText(/Партнёру эти слова не уходят/)).toBeVisible();
    await expect(request.getByRole("button", { name: "Отправить запрос" })).toBeDisabled();
    await preview.scrollIntoViewIfNeeded();
    await settledScreenshot(page, `leak3-b2-preview-missing-${String(width)}`);
    await expectNoViolations(page, "запрос цены: строка без названия для партнёра");

    await field.fill("Стрелочный перевод");
    await expect(request.getByRole("button", { name: "Отправить запрос" })).toBeEnabled();
    await settledScreenshot(page, `leak3-b2-preview-named-${String(width)}`);
    await expectNoViolations(page, "запрос цены: название подтверждено");
    await request.getByRole("button", { name: "Отправить запрос" }).click();
    await expect(page.getByText("Запрос ушёл на sales@steel.example")).toBeVisible();
    // в журнале — подтверждённое название, слов клиента нет
    const journal = page.getByRole("list", { name: "Запросы цены у партнёров" });
    await expect(journal.getByText(/Стрелочный перевод/)).toBeVisible();
    await expect(journal.getByText(/Чиланзар/)).toHaveCount(0);
  });
}
