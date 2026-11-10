import { appendFileSync } from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import {
  loginAndWait,
  settledScreenshot,
  spaGoto,
  waitForMotionEnd,
  partnerCard,
} from "./support/app";
import { chooseOption, pickFiles } from "./support/fields";

// CAT-1 (L0-2) на MSW: снабженец заводит иностранный завод без ИНН, загружает его прайс по шаблону (проверка ничего не
// пишет, отчёт с ошибками строк и изменениями на одобрение), применяет; в карточке позиции решает изменение от завода и
// видит, чего не хватает для публикации; у поставщика добавляет цену с Incoterms и смотрит историю. Названия выдуманы.
// axe (WCAG 2.1 AA) на каждом экране; снимки 1440 и 390 в docs/screens/cat-1/.

async function expectNoViolations(page: Page, context: string): Promise<void> {
  await waitForMotionEnd(page);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const found = results.violations.map(
    (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`,
  );
  const log = process.env["E2E_AXE_LOG"];
  if (log) {
    const width = page.viewportSize()?.width ?? 0;
    appendFileSync(log, `${context} · ${String(width)} px: нарушений ${String(found.length)}\n`);
  }
  expect(found, context).toEqual([]);
}

async function openCatalog(page: Page, query: string): Promise<void> {
  await spaGoto(page, `/erp/catalog${query}`);
  const heading = query.includes("part=import") ? "Загрузка прайса" : "Товары";
  await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
}

const PRICE_FILE = {
  name: "werk-nordlicht-price.xlsx",
  mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  buffer: Buffer.from("PK\u0003\u0004 sample price list"),
};

async function uploadScenario(page: Page, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width < 600 ? 844 : 900 });
  await loginAndWait(page, "supply@demo.example");
  await openCatalog(page, "?part=import");
  await expectNoViolations(page, "загрузка прайса");
  await settledScreenshot(page, "cat1-import-empty");

  // новый иностранный завод без ИНН
  await page.getByRole("button", { name: "Новый поставщик" }).click();
  const form = page.getByRole("dialog", { name: "Новый поставщик" });
  await form.getByLabel("Название").fill("Werk Nordlicht GmbH");
  await chooseOption(form.getByLabel("Страна"), "Германия");
  await chooseOption(form.getByLabel("Валюта цен"), "EUR");
  await form.getByLabel("Рег. номер").fill("HRB 000001");
  await form.getByLabel("Сам выпускает товар (изготовитель)").check();
  await expectNoViolations(page, "новый поставщик");
  await settledScreenshot(page, "cat1-new-supplier");
  await form.getByRole("button", { name: "Добавить" }).click();
  await expect(form).toBeHidden();

  // файл, срок цен, проверка
  await pickFiles(page.getByLabel("Файл прайса"), PRICE_FILE);
  await page.getByRole("button", { name: "Проверить" }).click();
  await expect(page.getByText("Проверка: ничего не записано")).toBeVisible();
  await expect(page.getByText("Неизвестная валюта «XYZ»")).toBeVisible();
  await expect(page.getByText("Кабель силовой ВВГнг-LS 3×2,5")).toBeVisible();
  await expectNoViolations(page, "отчёт проверки");
  await settledScreenshot(page, "cat1-import-checked");

  await page.getByRole("button", { name: "Применить" }).click();
  await expect(page.getByText("Прайс загружен")).toBeVisible();
  await expectNoViolations(page, "прайс загружен");
  await settledScreenshot(page, "cat1-import-applied");

  // карточка позиции: изменение от завода на одобрении, публикация
  await page.getByRole("button", { name: "Открыть позиции на одобрении" }).click();
  await page.getByRole("button", { name: /Открыть позицию Кабель силовой/ }).click();
  const card = page.getByRole("dialog", { name: "Кабель силовой ВВГнг 3×2,5" });
  await expect(card.getByText("Изменения от поставщиков")).toBeVisible();
  await expect(card.getByRole("button", { name: "Снять с публикации" })).toBeVisible();
  await expectNoViolations(page, "изменения от поставщиков");
  await settledScreenshot(page, "cat1-item-proposals");
  await card.getByRole("button", { name: "Отклонить изменение: Наименование" }).click();
  await expect(card.getByText("Изменения от поставщиков")).toHaveCount(0);
  await expect(card.getByText("Кабель силовой ВВГнг 3×2,5").first()).toBeVisible();
}

test.describe("CAT-1: загрузка прайса поставщика", () => {
  test.skip(({ isMobile }) => isMobile, "1440; телефон — отдельный блок @mobile");

  test("иностранный завод без ИНН → прайс по шаблону → проверка → применить → решение в карточке", async ({
    page,
  }) => {
    await uploadScenario(page, 1440);
  });

  test("цена поставщика вручную с Incoterms и история; неполную карточку не опубликовать", async ({
    page,
  }) => {
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/crm/clients?partner=3&panel=open&tab=card");
    const supplier = partnerCard(page, "ИП «Восточный склад»");
    await supplier.getByRole("button", { name: "Добавить цену" }).click();
    const form = page.getByRole("dialog", { name: /Цена поставщика/ });
    await chooseOption(form.getByLabel("Позиция"), "Реле защиты РЗ-1 · RT-0002");
    await form.getByLabel(/Цена закупки/).fill("295");
    await chooseOption(form.getByLabel("Базис поставки (Incoterms)"), "FCA · Free Carrier");
    await expectNoViolations(page, "цена поставщика");
    await settledScreenshot(page, "cat1-offer-create");
    await form.getByRole("button", { name: "Добавить" }).click();
    await expect(form).toBeHidden();
    await supplier
      .getByRole("button", { name: "История цены по позиции Реле защиты РЗ-1" })
      .click();
    const history = page.getByRole("dialog", { name: /История цены/ });
    await expect(history.getByText("вручную")).toBeVisible();
    await expectNoViolations(page, "история цены");
    await settledScreenshot(page, "cat1-offer-history");

    await openCatalog(page, "?item=5");
    const card = page.getByRole("dialog", { name: "Пусконаладочные работы" });
    await expect(card.getByText(/Для публикации заполните: категория, код ТН ВЭД/)).toBeVisible();
    await expect(card.getByRole("button", { name: "Опубликовать" })).toBeDisabled();
  });
});

test.describe("CAT-1 на телефоне @mobile", () => {
  test("тот же путь на 390: форма, отчёт и карточка без горизонтальной прокрутки", async ({
    page,
  }) => {
    await uploadScenario(page, 390);
    const overflow = await page.evaluate(
      "document.documentElement.scrollWidth - document.documentElement.clientWidth",
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
