import { appendFileSync } from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

import {
  loginAndWait,
  openAvatarMenu,
  settledScreenshot,
  spaGoto,
  waitForMotionEnd,
} from "./support/app";
import { pickFiles } from "./support/fields";

// Admin · Компания на MSW (W13-A3): каждое действие экрана, права, axe на 1440, 1280 и 390, снимки (`E2E_SCREENSHOT_DIR`).
const WIDTHS = [1440, 1280, 390] as const;

/** Минимальный настоящий PNG 1×1: файл уходит как `multipart/form-data` через service worker MSW. */
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAHtPlwQAAAABJRU5ErkJggg==",
  "base64",
);

const TABS = [
  ["details", "Реквизиты компании"],
  ["brand", "Бланк и бренд документов"],
  ["numbering", "Нумерация документов"],
  ["quote", "Условия КП по умолчанию"],
  ["charges", "Статьи расхода КП"],
  ["templates", "Шаблоны документов и писем"],
  ["reference", "Справочники ERP"],
  ["categories", "Категории каталога и запросы на них"],
  ["platform", "Платформенные настройки"],
] as const;

async function expectNoViolations(page: Page, context: string): Promise<void> {
  await waitForMotionEnd(page);
  // Образцы документов — изолированные рамки (`sandbox=""`): скрипты в них не выполняются, axe не может опросить рамку и
  // ждёт её до таймаута. Содержимое образца — документ ERP, а не интерфейс Платформы; сама рамка (имя, размер) проверяется.
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .exclude("iframe.pf-co-frame")
    .analyze();
  // Итог axe рядом со снимками (`axe-results.txt`), как в других задачах.
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (dir) {
    appendFileSync(
      `${dir}/axe-results.txt`,
      `${context}: axe violations=${String(results.violations.length)}\n`,
    );
  }
  expect(
    results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`),
    context,
  ).toEqual([]);
}

async function openCompany(page: Page, tab: string): Promise<void> {
  await spaGoto(page, `/admin/company?tab=${tab}`);
  await expect(page.getByRole("heading", { level: 1, name: "Компания и бланки" })).toBeVisible();
  const title = TABS.find(([key]) => key === tab)?.[1] ?? "";
  await expect(page.getByRole("heading", { level: 2, name: title })).toBeVisible();
}

async function signOut(page: Page): Promise<void> {
  await openAvatarMenu(page);
  await page.getByRole("menuitem", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login/);
}

/**
 * Выбор в antd Select с поиском: фокус, ввод части названия, Enter. Нажатием мыши список не открываем: поле ввода лежит под
 * подписью выбранного значения, а пункты списка появляются с анимацией antd (под нагрузкой «нажать» ждёт их долго).
 */
async function choose(page: Page, select: Locator, text: string): Promise<void> {
  await select.focus();
  await page.keyboard.type(text);
  await page.keyboard.press("Enter");
  await expect(
    select.locator("xpath=ancestor::div[contains(@class,'ant-select')][1]"),
  ).toContainText(text);
}

const toast = (page: Page, text: string) => page.locator(".ant-message").getByText(text);

test.describe("Компания: права и меню", () => {
  test.skip(({ isMobile }) => isMobile, "сценарий на десктопе; ширины проверяет блок axe");

  test("менеджер: пункта «Компания» в меню нет, по адресу — «Нет доступа»", async ({ page }) => {
    await loginAndWait(page, "manager@demo.example");
    await expect(page.getByRole("link", { name: "Компания и бланки" })).toHaveCount(0);
    await spaGoto(page, "/admin/company");
    await expect(page.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
  });

  test("директор и администратор видят пункт «Компания» в меню Admin и открывают раздел", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/admin/org");
    await page
      .getByRole("navigation", { name: "Разделы модуля" })
      .getByRole("link", { name: "Компания и бланки" })
      .click();
    await expect(page).toHaveURL(/\/admin\/company/);
    await expect(page.getByRole("heading", { level: 1, name: "Компания и бланки" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Реквизиты" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await signOut(page);

    await loginAndWait(page, "admin@demo.example");
    await openCompany(page, "details");
  });
});

test.describe("Компания: реквизиты, бланк, нумерация, условия КП", () => {
  test.skip(({ isMobile }) => isMobile, "сценарий на десктопе");

  test("реквизиты: правка телефона сохраняется и переживает перезагрузку; логотип загружается и удаляется", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await openCompany(page, "details");
    // Без правок бар сохранения невидим (UX-1b, S6)
    await expect(page.getByRole("button", { name: "Сохранить реквизиты" })).toBeHidden();

    await page.getByLabel("Телефон").fill("+998 11 111 11 11");
    await expect(
      page.getByText("Реквизиты обновятся в карточке своей компании в ERP."),
    ).toBeVisible();
    await page.getByRole("button", { name: "Сохранить реквизиты" }).click();
    await expect(toast(page, "Сохранено")).toBeVisible();

    await page.getByLabel(/^ИНН/).fill("12");
    await page.getByRole("button", { name: "Сохранить реквизиты" }).click();
    await expect(page.getByText("ИНН — 9 цифр")).toBeVisible();
    await page.getByLabel(/^ИНН/).fill("123456789");

    // Тосты не накладываются на снимок: ждём, пока уйдёт «Сохранено», и только потом загружаем файл.
    await expect(page.locator(".ant-message-notice")).toHaveCount(0);
    await pickFiles(page.getByLabel("Выбрать файл: Логотип компании"), {
      name: "logo.png",
      mimeType: "image/png",
      buffer: PNG,
    });
    await expect(toast(page, "Логотип загружен")).toBeVisible();
    await expect(page.getByRole("img", { name: "Логотип" })).toBeVisible();
    await expect(page.locator(".ant-message-notice")).toHaveCount(1);
    await settledScreenshot(page, "company-details-logo");

    await page.reload();
    await expect(page.getByRole("heading", { level: 1, name: "Компания и бланки" })).toBeVisible();
    await expect(page.getByLabel("Телефон")).toHaveValue("+998 11 111 11 11");
    await page.getByRole("button", { name: "Удалить логотип" }).click();
    const confirm = page.getByRole("dialog", { name: "Удалить логотип компании?" });
    await expect(confirm.getByText("Что произойдёт")).toBeVisible();
    await confirm.getByRole("button", { name: "Удалить логотип" }).click();
    await expect(toast(page, "Логотип удалён")).toBeVisible();
    await expect(page.getByText("Нет логотипа")).toBeVisible();
  });

  test("бланк и бренд: образец меняется до сохранения, вид документа переключается, цвет проверяется", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await openCompany(page, "brand");
    const frame = page.frameLocator('iframe[title="Образец: КП"]');
    await expect(frame.getByText("Коммерческое предложение", { exact: false })).toBeVisible();

    await page.getByLabel("Основной цвет", { exact: true }).fill("#047857");
    await expect(frame.locator("strong")).toHaveCSS("color", "rgb(4, 120, 87)");
    await page.locator(".ant-segmented-item-label", { hasText: "Договор" }).click();
    await expect(
      page.frameLocator('iframe[title="Образец: Договор"]').getByText("Договор поставки", {
        exact: false,
      }),
    ).toBeVisible();
    await settledScreenshot(page, "company-brand-edited");

    await page.getByLabel("Основной цвет", { exact: true }).fill("red");
    await page.getByRole("button", { name: "Сохранить бланк" }).click();
    await expect(page.getByText("Цвет в формате #RRGGBB")).toBeVisible();
    await page.getByLabel("Основной цвет", { exact: true }).fill("#047857");
    await page.getByLabel("Подписант", { exact: true }).fill("Демо Подписантов");
    await page.getByRole("button", { name: "Сохранить бланк" }).click();
    await expect(toast(page, "Сохранено")).toBeVisible();

    await pickFiles(page.getByLabel("Выбрать файл: Логотип бланка"), {
      name: "brand.png",
      mimeType: "image/png",
      buffer: PNG,
    });
    await expect(toast(page, "Логотип загружен")).toBeVisible();
  });

  test("нумерация: образец номеров по черновику, ошибка маски и занятого префикса, сохранение", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await openCompany(page, "numbering");
    const samples = page.getByRole("list", { name: "Образец номеров" });
    await expect(samples.getByText(/DEMO-КП-\d{4}-00001/)).toBeVisible();

    await page.getByLabel("Префикс нумерации").fill("ACME");
    await expect(samples.getByText(/ACME-КП-\d{4}-00001/)).toBeVisible();
    await page.getByLabel("Ширина счётчика").fill("6");
    await expect(samples.getByText(/ACME-КП-\d{4}-000001/)).toBeVisible();
    await expect(page.getByText("Уже выданные номера не меняются.")).toBeVisible();

    await page.getByLabel("Маска номера").fill("{type}-");
    await expect(page.getByText("В маске обязателен токен {seq}")).toBeVisible();
    await expect(page.getByRole("button", { name: "Сохранить нумерацию" })).toBeDisabled();
    await page.getByLabel("Маска номера").fill("{prefix}{type}-{YYYY}-{seq}");

    await page.getByLabel("Префикс нумерации").fill("TAKEN");
    await page.getByRole("button", { name: "Сохранить нумерацию" }).click();
    await expect(page.getByText("Префикс занят другой компанией")).toBeVisible();
    await settledScreenshot(page, "company-numbering-error");

    await page.getByLabel("Префикс нумерации").fill("ACME");
    await page.getByRole("button", { name: "Сохранить нумерацию" }).click();
    await expect(toast(page, "Нумерация сохранена")).toBeVisible();
  });

  test("условия КП: директор меняет маржу, администратор маржи не видит", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await openCompany(page, "quote");
    await page.getByLabel("Минимальная маржа, %").fill("6");
    await page.getByLabel("Срок действия КП, дней").fill("30");
    await page.getByRole("button", { name: "Сохранить условия" }).click();
    await expect(toast(page, "Сохранено")).toBeVisible();
    await signOut(page);

    await loginAndWait(page, "admin@demo.example");
    await openCompany(page, "quote");
    await expect(page.getByLabel("Срок действия КП, дней")).toHaveValue("30");
    await expect(page.getByLabel("Минимальная маржа, %")).toHaveCount(0);
    await expect(page.getByText(/Поля маржи скрыты/)).toBeVisible();
  });
});

test.describe("Компания: статьи расхода, шаблоны, справочники", () => {
  test.skip(({ isMobile }) => isMobile, "сценарий на десктопе");

  test("статьи расхода: добавить, изменить, удалить с «Что произойдёт»", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await openCompany(page, "charges");
    await page.getByRole("button", { name: "Добавить статью" }).click();
    const dialog = page.getByRole("dialog", { name: "Новая статья расхода" });
    await choose(page, dialog.getByLabel("Базис поставки"), "DAP");
    await choose(page, dialog.getByLabel("Статья", { exact: true }), "Доставка до склада");
    await dialog.getByLabel("Сумма").fill("250");
    await settledScreenshot(page, "company-charges-add");
    await dialog.getByRole("button", { name: "Сохранить" }).click();
    await expect(toast(page, "Сохранено")).toBeVisible();
    await expect(page.getByRole("row", { name: /Доставка до склада/ })).toContainText("250");

    await page.getByRole("button", { name: "Изменить: Доставка до склада · DAP" }).click();
    const edit = page.getByRole("dialog", { name: "Изменить статью расхода" });
    await edit.getByLabel("Сумма").fill("300");
    await edit.getByRole("button", { name: "Сохранить" }).click();
    await expect(page.getByRole("row", { name: /Доставка до склада/ })).toContainText("300");

    await page.getByRole("button", { name: "Удалить: Доставка до склада · DAP" }).click();
    const confirm = page.getByRole("dialog", { name: /Удалить статью/ });
    await expect(confirm.getByText("Что произойдёт")).toBeVisible();
    await confirm.getByRole("button", { name: "Удалить" }).click();
    await expect(page.getByRole("row", { name: /Доставка до склада/ })).toHaveCount(0);
  });

  test("шаблоны документов: копия образца, правка с образцом, нельзя удалить используемый", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await openCompany(page, "templates");
    await page
      .getByRole("button", { name: "Скопировать к себе: Образец: договор поставки" })
      .click();
    const copy = page.getByRole("dialog", { name: /Скопировать/ });
    await copy.getByLabel("Название").fill("Договор поставки (рельсы)");
    await copy.getByRole("button", { name: "Скопировать к себе" }).click();
    await expect(toast(page, "Копия создана")).toBeVisible();

    await page.getByRole("button", { name: "Изменить: Договор поставки (рельсы)" }).click();
    const editor = page.getByRole("dialog", { name: "Изменить шаблон документа" });
    const body = editor.getByLabel(/^Текст шаблона/);
    await body.fill(
      "<p>{{buyer_name}} {{mystery}}</p>{{doc.spec_table}}{{doc.totals}}{{doc.requisites_and_signatures}}",
    );
    await expect(editor.getByText("Неизвестная подстановка {{mystery}}")).toBeVisible();
    await expect(
      editor.frameLocator('iframe[title="Образец документа по шаблону"]').getByText("[buyer_name]"),
    ).toBeVisible();
    await settledScreenshot(page, "company-templates-editor");
    await editor.getByRole("button", { name: "Сохранить" }).click();
    await expect(toast(page, "Сохранено")).toBeVisible();

    await page.getByRole("button", { name: "Удалить: Договор поставки (наш)" }).click();
    const confirm = page.getByRole("dialog", { name: /Удалить шаблон/ });
    await confirm.getByRole("button", { name: "Удалить" }).click();
    await expect(
      confirm.getByText("По шаблону уже оформлены документы. Отключите его вместо удаления."),
    ).toBeVisible();
    await confirm.getByRole("button", { name: "Отмена" }).click();

    await page.getByRole("button", { name: "Удалить: Договор поставки (рельсы)" }).click();
    await page
      .getByRole("dialog", { name: /Удалить шаблон/ })
      .getByRole("button", { name: "Удалить" })
      .click();
    await expect(toast(page, "Шаблон удалён")).toBeVisible();
  });

  test("шаблоны писем: включить шаблон, показать образец, создать новый", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await openCompany(page, "templates");
    await page.locator(".ant-segmented-item-label", { hasText: "Шаблоны писем" }).click();
    await page.getByRole("button", { name: "Изменить: quote_sent" }).click();
    const editor = page.getByRole("dialog", { name: "Изменить шаблон письма" });
    await editor.getByLabel("Шаблон действует").check();
    await expect(editor.getByText(/сразу заменит файловый/)).toBeVisible();
    await editor.getByRole("button", { name: "Показать образец" }).click();
    await expect(
      editor.frameLocator('iframe[title="Образец письма"]').getByText("Направляем КП"),
    ).toBeVisible();
    await settledScreenshot(page, "company-email-editor");
    await editor.getByRole("button", { name: "Сохранить" }).click();
    await expect(toast(page, "Сохранено")).toBeVisible();

    await page.getByRole("button", { name: "Создать шаблон письма" }).click();
    const create = page.getByRole("dialog", { name: "Новый шаблон письма" });
    await create.getByLabel("Ключ письма").fill("act_issued");
    await create.getByLabel("Тема").fill("Акт {{number}}");
    await create.getByLabel("Текст письма", { exact: true }).fill("Акт выпущен.");
    await create.getByRole("button", { name: "Сохранить" }).click();
    await expect(page.getByRole("row", { name: /act_issued/ })).toBeVisible();

    await page.getByRole("button", { name: "Удалить: act_issued" }).click();
    await page
      .getByRole("dialog", { name: /Удалить шаблон/ })
      .getByRole("button", { name: "Удалить" })
      .click();
    await expect(page.getByRole("row", { name: /act_issued/ })).toHaveCount(0);
  });

  test("справочники: добавить страну, отключить валюту, используемую строку не удалить", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await openCompany(page, "reference");
    await page.getByRole("button", { name: "Добавить строку" }).click();
    const dialog = page.getByRole("dialog", { name: "Новая строка справочника" });
    await dialog.getByLabel("Код", { exact: true }).fill("TR");
    await dialog.getByLabel("Название").fill("Турция");
    await dialog.getByRole("button", { name: "Сохранить" }).click();
    await expect(page.getByRole("row", { name: /Турция/ })).toBeVisible();

    await page.getByRole("button", { name: "Удалить: Узбекистан" }).click();
    const confirm = page.getByRole("dialog", { name: /Удалить/ });
    await confirm.getByRole("button", { name: "Удалить" }).click();
    await expect(
      confirm.getByText("Строка используется в документах и данных. Отключите её вместо удаления."),
    ).toBeVisible();
    await confirm.getByRole("button", { name: "Отмена" }).click();

    await page.locator(".ant-segmented-item-label", { hasText: "Валюты" }).click();
    await page.getByRole("button", { name: "Отключить: Евро" }).click();
    await expect(page.getByRole("row", { name: /Евро/ })).toContainText("Отключена");
    await page.getByRole("button", { name: "Включить: Евро" }).click();
    await expect(page.getByRole("row", { name: /Евро/ })).toContainText("Активна");
    await settledScreenshot(page, "company-reference-currencies");
  });
});

test.describe("Компания: категории, запросы, платформенные настройки", () => {
  test.skip(({ isMobile }) => isMobile, "сценарий на десктопе");

  test("категории: добавить подкатегорию, переименовать, удалить; с подкатегориями — отказ словами", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await openCompany(page, "categories");
    await page
      .getByRole("button", { name: "Подкатегория: добавить в «Электрооборудование»" })
      .click();
    const dialog = page.getByRole("dialog", { name: "Новая категория" });
    await dialog.getByLabel("Название").fill("Кабели");
    await dialog.getByRole("button", { name: "Сохранить" }).click();
    await expect(page.getByText("Кабели", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Изменить: Кабели" }).click();
    const edit = page.getByRole("dialog", { name: "Изменить категорию" });
    await edit.getByLabel("Название").fill("Силовые кабели");
    await edit.getByRole("button", { name: "Сохранить" }).click();
    await expect(page.getByText("Силовые кабели", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Удалить: Подвижной состав" }).click();
    const blocked = page.getByRole("dialog", { name: /Удалить категорию/ });
    await blocked.getByRole("button", { name: "Удалить" }).click();
    await expect(
      blocked.getByText("У категории есть подкатегории. Сначала перенесите или удалите их."),
    ).toBeVisible();
    await blocked.getByRole("button", { name: "Отмена" }).click();

    await page.getByRole("button", { name: "Удалить: Силовые кабели" }).click();
    await page
      .getByRole("dialog", { name: /Удалить категорию/ })
      .getByRole("button", { name: "Удалить" })
      .click();
    await expect(page.getByText("Силовые кабели", { exact: true })).toHaveCount(0);
  });

  test("запросы на категории: администратор отклоняет с причиной и одобряет с выбором категории", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openCompany(page, "categories");
    await page.locator(".ant-segmented-item-label", { hasText: "Запросы (2)" }).click();
    await expect(page.getByRole("row", { name: /Тормозные колодки/ })).toContainText(
      "На рассмотрении",
    );
    await settledScreenshot(page, "company-category-requests");

    await page.getByRole("button", { name: "Отклонить запрос: Тормозные колодки" }).click();
    const reject = page.getByRole("dialog", { name: /Отклонить запрос/ });
    await expect(reject.getByText("Что произойдёт")).toBeVisible();
    await expect(reject.getByText("Причина обязательна")).toBeVisible();
    await reject.getByLabel("Причина отказа").fill("Дубль существующей категории");
    await settledScreenshot(page, "company-category-reject");
    await reject.getByRole("button", { name: "Отклонить" }).click();
    await expect(toast(page, "Запрос отклонён")).toBeVisible();
    await expect(page.getByRole("row", { name: /Тормозные колодки/ })).toContainText("Отклонён");
    await expect(page.getByRole("row", { name: /Тормозные колодки/ })).toContainText(
      "Дубль существующей категории",
    );

    await page.getByRole("button", { name: "Одобрить запрос: Стрелочные переводы" }).click();
    const approve = page.getByRole("dialog", { name: /Одобрить запрос/ });
    await expect(
      approve.getByText(/Сама категория в каталоге этим действием не создаётся/),
    ).toBeVisible();
    await choose(page, approve.getByLabel("Категория, которую вы завели для запроса"), "Крепёж");
    await approve.getByRole("button", { name: "Одобрить" }).click();
    await expect(toast(page, "Запрос одобрен")).toBeVisible();
    await expect(page.getByRole("row", { name: /Стрелочные переводы/ })).toContainText("Одобрен");
  });

  test("запросы: директору ERP решение не доверяет — отказ словами, запрос остаётся", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await openCompany(page, "categories");
    await page.locator(".ant-segmented-item-label", { hasText: "Запросы (2)" }).click();
    await page.getByRole("button", { name: "Одобрить запрос: Тормозные колодки" }).click();
    const approve = page.getByRole("dialog", { name: /Одобрить запрос/ });
    await choose(page, approve.getByLabel("Категория, которую вы завели для запроса"), "Крепёж");
    await approve.getByRole("button", { name: "Одобрить" }).click();
    await expect(approve.getByText(/ERP не разрешила действие/)).toBeVisible();
  });

  test("платформенные настройки: администратор меняет НДС; директору ERP откажет", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openCompany(page, "platform");
    await expect(page.getByText(/1 USD = 12\s650,50 сум/)).toBeVisible();
    await page.getByLabel("Ставка НДС, %").fill("15");
    await page.getByRole("button", { name: "Сохранить ставку НДС" }).click();
    await expect(toast(page, "Сохранено")).toBeVisible();
    await signOut(page);

    await loginAndWait(page, "director@demo.example");
    await openCompany(page, "platform");
    await page.getByLabel("Ставка НДС, %").fill("13");
    await page.getByRole("button", { name: "Сохранить ставку НДС" }).click();
    await expect(page.getByText(/ERP не разрешила действие/)).toBeVisible();
  });
});

test.describe("Курс USD → UZS: ручной ввод (W13C-F6)", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of [1440, 390] as const) {
    test(`ввод курса, ошибка у поля, журнал на ${String(width)}: axe без нарушений, снимки`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "admin@demo.example");
      await openCompany(page, "platform");
      const section = page.getByRole("region", { name: "Курс USD → UZS" });
      await expect(section.getByText(/1 USD = 12\s650,50 сум/)).toBeVisible();
      await expect(section.getByText("Автозагрузка (ЦБ РУз)")).toBeVisible();
      await expect(section.getByRole("region", { name: "Журнал курса" })).toBeVisible();
      await expectNoViolations(page, `fx default ${String(width)}`);
      await settledScreenshot(page, "fx-rate-default");

      // ошибка у поля: ноль не курс, на сервер не уходит
      await section.getByLabel("Курс, сум за 1 USD").fill("0");
      await section.getByRole("button", { name: "Сохранить курс" }).click();
      await expect(section.getByText(/Курс — число больше нуля/)).toBeVisible();
      await expectNoViolations(page, `fx error ${String(width)}`);
      await settledScreenshot(page, "fx-rate-error");

      // ввод запятой: курс, источник и журнал обновились
      await section.getByLabel("Курс, сум за 1 USD").fill("12700,5");
      await section.getByRole("button", { name: "Сохранить курс" }).click();
      await expect(toast(page, "Курс сохранён")).toBeVisible();
      await expect(section.getByText(/1 USD = 12\s700,50 сум/)).toBeVisible();
      await expect(
        section.locator(".ant-tag", { hasText: "Введён вручную" }).first(),
      ).toBeVisible();
      await expect(
        section.getByRole("row", { name: /12\s700,50/ }).getByText("Ввод вручную"),
      ).toBeVisible();
      await expectNoViolations(page, `fx saved ${String(width)}`);
      await settledScreenshot(page, "fx-rate-saved");
      await section.getByRole("region", { name: "Журнал курса" }).scrollIntoViewIfNeeded();
      await settledScreenshot(page, "fx-rate-journal");
    });
  }
});

test.describe("Компания: axe и снимки", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`все вкладки на ${String(width)}: axe без нарушений, снимки`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      for (const [tab] of TABS) {
        await openCompany(page, tab);
        // данные вкладки пришли: форма, список или таблица, а не скелетон
        await expect(page.locator(".ant-skeleton, [data-pf-skeleton]")).toHaveCount(0);
        await expect(page.locator(".pf-co-body")).toBeVisible();
        if (tab === "brand") await expect(page.locator('iframe[title^="Образец"]')).toBeVisible();
        if (tab === "numbering") {
          await expect(
            page.getByRole("list", { name: "Образец номеров" }).getByText(/00001/).first(),
          ).toBeVisible();
        }
        await expectNoViolations(page, `${tab} ${String(width)}`);
        await settledScreenshot(page, `company-${tab}`);
      }
    });

    test(`окна и вторые разделы на ${String(width)}: axe без нарушений, снимки`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "admin@demo.example");

      await openCompany(page, "templates");
      await page.getByRole("button", { name: "Изменить: Акт приёмки" }).click();
      const editor = page.getByRole("dialog", { name: "Изменить шаблон документа" });
      await expect(editor.frameLocator("iframe").getByText("[seller_name]")).toBeVisible();
      await expectNoViolations(page, `document editor ${String(width)}`);
      await settledScreenshot(page, "company-templates-editor-modal");
      await editor.getByRole("button", { name: "Отмена" }).click();

      await page.locator(".ant-segmented-item-label", { hasText: "Шаблоны писем" }).click();
      await expect(page.getByRole("row", { name: /invoice_issued/ })).toBeVisible();
      await expectNoViolations(page, `email templates ${String(width)}`);
      await settledScreenshot(page, "company-templates-emails");

      await openCompany(page, "reference");
      await page.locator(".ant-segmented-item-label", { hasText: "Базисы поставки" }).click();
      await expect(page.getByRole("row", { name: /DAP/ })).toBeVisible();
      await expectNoViolations(page, `reference ${String(width)}`);
      await settledScreenshot(page, "company-reference-basis");

      await openCompany(page, "categories");
      await page.locator(".ant-segmented-item-label", { hasText: "Запросы (2)" }).click();
      await expect(page.getByRole("row", { name: /Тормозные колодки/ })).toBeVisible();
      await expectNoViolations(page, `requests ${String(width)}`);
      await settledScreenshot(page, "company-category-requests-list");
      await page.getByRole("button", { name: "Отклонить запрос: Тормозные колодки" }).click();
      await expect(page.getByRole("dialog", { name: /Отклонить запрос/ })).toBeVisible();
      await expectNoViolations(page, `reject modal ${String(width)}`);
      await settledScreenshot(page, "company-category-reject-modal");
    });
  }
});
