import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";
import { chooseOption, fillDate, pickFiles } from "./support/fields";

// CAT-CARD-1 на MSW: карточка товара в Платформе. Снабженец: фото (загрузка, главное, порядок, удаление с подтверждением),
// документ с видом из справочника, номером, органом и сроком (загрузка прямо из карточки), страна происхождения и гарантия с
// умолчаниями, отметка «Истёк» у документа с прошедшим сроком. axe (WCAG 2.1 AA) на каждом шаге; снимки 1440 и 390 —
// docs/screens/CAT-CARD-1/. Названия и файлы выдуманы.

const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);
const PDF = Buffer.from("%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n");

async function openCard(page: Page): Promise<ReturnType<Page["getByRole"]>> {
  await spaGoto(page, "/erp/catalog?item=1");
  const card = page.getByRole("dialog", { name: "Кабель силовой ВВГнг 3×2,5" });
  await expect(card.getByRole("list", { name: "Фото позиции" })).toBeVisible();
  return card;
}

const gallery = (card: ReturnType<Page["getByRole"]>) =>
  card.getByRole("list", { name: "Фото позиции" }).getByRole("listitem");

test.describe("Карточка товара", () => {
  test.skip(({ isMobile }) => isMobile, "сценарий на десктопе; телефон — отдельный тест @mobile");

  test("фото: загрузить, сделать главным, переставить, удалить; десять — предел", async ({
    page,
  }) => {
    await loginAndWait(page, "supply@demo.example");
    const card = await openCard(page);

    await expect(gallery(card)).toHaveCount(3);
    await expect(card.getByText("3 из 10")).toBeVisible();
    await expect(card.getByText("Главное")).toHaveCount(1);
    await expect(gallery(card).first().getByText("Главное")).toBeVisible();
    await expect(card.getByText(/квадрат от 900 px на светлом фоне/)).toBeVisible();
    await expectNoViolations(page, "карточка: фото");
    await settledScreenshot(page, "card-photos");

    // загрузка: фото добавляется в конец
    await pickFiles(card.locator('input[type="file"]'), {
      name: "side.png",
      mimeType: "image/png",
      buffer: PNG,
    });
    await expect(gallery(card)).toHaveCount(4);
    await expect(card.getByText("4 из 10")).toBeVisible();

    // главное — звезда и слово у выбранного
    await card.getByRole("button", { name: "Сделать главным фото 4" }).click();
    await expect(gallery(card).nth(3).getByText("Главное")).toBeVisible();
    await expect(card.getByText("Главное")).toHaveCount(1);

    // порядок: главное поднимается на второе место
    await card.getByRole("button", { name: "Поднять фото 4" }).click();
    await expect(gallery(card).nth(2).getByText("Главное")).toBeVisible();
    await expect(card.getByRole("button", { name: "Поднять фото 1" })).toBeDisabled();

    // удаление главного — с подтверждением, следующее становится главным
    await card.getByRole("button", { name: "Удалить фото 3" }).click();
    const confirm = page.getByRole("dialog", { name: "Удалить фото 3?" });
    await expectNoViolations(page, "карточка: удаление фото");
    await settledScreenshot(page, "card-photo-delete");
    await confirm.getByRole("button", { name: "Удалить", exact: true }).click();
    await expect(confirm).toBeHidden();
    await expect(gallery(card)).toHaveCount(3);
    await expect(card.getByText("Главное")).toHaveCount(1);

    // предел: ещё семь фото — кнопка закрыта, сказано словами
    await pickFiles(
      card.locator('input[type="file"]'),
      Array.from({ length: 7 }, (_, n) => ({
        name: `more-${String(n)}.png`,
        mimeType: "image/png",
        buffer: PNG,
      })),
    );
    await expect(gallery(card)).toHaveCount(10);
    await expect(card.getByRole("button", { name: /Добавить фото/ })).toBeDisabled();
    await expect(card.getByText(/Достигнут предел: 10 фото/)).toBeVisible();
    await expectNoViolations(page, "карточка: десять фото");
  });

  test("документ с видом, номером, органом и сроком; истёкший помечен; страна и гарантия", async ({
    page,
  }) => {
    await loginAndWait(page, "supply@demo.example");
    const card = await openCard(page);

    const docs = card.getByRole("list", { name: "Документы позиции" });
    await expect(docs.getByText("Сертификат соответствия на кабель")).toBeVisible();
    await expect(docs.getByText(/RU-0042-2026/)).toBeVisible();
    await expect(docs.getByText(/до 11\.01\.2027/)).toBeVisible();

    // загрузка из карточки: вид из справочника подставляет «Видно клиенту»
    await card.getByRole("button", { name: "Добавить документ" }).click();
    const form = page.getByRole("dialog", { name: "Добавить документ" });
    await pickFiles(form.getByLabel("Файл"), {
      name: "decl.pdf",
      mimeType: "application/pdf",
      buffer: PDF,
    });
    await chooseOption(form.getByRole("combobox", { name: "Вид" }), "Декларация о соответствии");
    await expect(form.getByRole("checkbox", { name: "Видно клиенту" })).toBeChecked();
    await form.getByLabel("Номер").fill("ЕАЭС N RU Д-UZ.0042");
    await form.getByLabel("Кем выдан").fill("Орган по сертификации (демо)");
    await fillDate(form.getByLabel("Выдан", { exact: true }), "2026-01-15");
    await fillDate(form.getByLabel("Действует до"), "2026-06-30");
    await expectNoViolations(page, "карточка: документ");
    await settledScreenshot(page, "card-doc-form");
    await form.getByRole("button", { name: "Загрузить", exact: true }).click();
    await expect(form).toBeHidden();

    // срок прошёл — отметка «Истёк» у сотрудника
    const added = docs.getByRole("listitem").filter({ hasText: "decl" });
    await expect(added.getByText("ЕАЭС N RU Д-UZ.0042")).toBeVisible();
    await expect(added.getByText("Истёк")).toBeVisible();
    await expectNoViolations(page, "карточка: документы");
    await settledScreenshot(page, "card-docs");

    // из карточки — в «Техдокументацию»: ждём смену экрана
    await added.getByRole("link", { name: "decl" }).click();
    await expect(page).toHaveURL(/\/erp\/docs\?doc=/);
    await expect(page.getByRole("heading", { level: 1, name: "Документация" })).toBeVisible();
    const docCard = page.getByRole("dialog", { name: "decl" });
    await expect(docCard.getByText("ЕАЭС N RU Д-UZ.0042")).toBeVisible();
    await expect(docCard.getByText("Орган по сертификации (демо)")).toBeVisible();
    await expectNoViolations(page, "документ: карточка файла");
    await docCard
      .getByRole("button", { name: /Закрыть|Close/ })
      .first()
      .click();

    // страна происхождения и гарантия: умолчания видны, свои значения побеждают
    const again = await openCard(page);
    await expect(again.getByText("12 мес. (по умолчанию компании)")).toBeVisible();
    await again.getByRole("button", { name: "Изменить позицию" }).click();
    const edit = page.getByRole("dialog", { name: "Изменить позицию" });
    await expect(edit.getByText(/Пусто — 12 мес., как у компании/)).toBeVisible();
    await chooseOption(edit.getByLabel("Страна происхождения"), "Германия");
    await edit.getByLabel("Гарантия, мес.").fill("24");
    await edit.getByLabel("Условия гарантии").fill("Замена при заводском браке");
    await expectNoViolations(page, "карточка: форма страны и гарантии");
    await settledScreenshot(page, "card-form");
    await edit.getByRole("button", { name: "Сохранить" }).click();
    await expect(edit).toBeHidden();
    await expect(again.getByText("24 мес.", { exact: true })).toBeVisible();
    await expect(again.getByText("Замена при заводском браке")).toBeVisible();
    await expectNoViolations(page, "карточка: страна и гарантия");
    await settledScreenshot(page, "card-origin-warranty");
  });

  test("менеджер видит фото и документы, но не меняет", async ({ page }) => {
    await loginAndWait(page, "manager@demo.example");
    const card = await openCard(page);

    await expect(gallery(card)).toHaveCount(3);
    await expect(card.getByRole("button", { name: /Добавить фото|Добавить документ/ })).toHaveCount(
      0,
    );
    await expect(card.getByRole("button", { name: /Удалить фото/ })).toHaveCount(0);
  });
});

test("карточка товара на телефоне: фото и документы без горизонтальной прокрутки @mobile", async ({
  page,
}, testInfo) => {
  await loginAndWait(page, "supply@demo.example");
  const card = await openCard(page);
  await expect(card.getByText("3 из 10")).toBeVisible();
  await expect(card.getByRole("list", { name: "Документы позиции" })).toBeVisible();
  const overflow = await page.evaluate<number>(
    "document.documentElement.scrollWidth - document.documentElement.clientWidth",
  );
  expect(overflow, `ширина ${testInfo.project.name}`).toBeLessThanOrEqual(0);
  await expectNoViolations(page, "карточка на телефоне");
  await card.getByRole("heading", { name: /Фото/ }).scrollIntoViewIfNeeded();
  await settledScreenshot(page, "card-mobile-photos");
  await card.getByRole("heading", { name: /Документы/ }).scrollIntoViewIfNeeded();
  await settledScreenshot(page, "card-mobile-docs");
});
