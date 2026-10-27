import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// CRM · База знаний на MSW (W13-A5): каждое действие экрана — поиск «Что найдёт бот», карточка документа, выключение и включение,
// переиндексация, загрузка файла (формат, размер, тип), ручной ввод, пробелы (создать документ, привязать, игнорировать, вернуть),
// песочница (диалог, «Почему так», «Начать заново»); менеджер и директор читают без кнопок изменения; axe (WCAG 2.1 AA) на всех
// вкладках и формах; снимки 1440 и 390 для PR.
const WIDTHS = [1440, 390] as const;
const PANEL = "#pf-context-panel";

async function expectNoViolations(page: Page, context: string): Promise<void> {
  await waitForMotionEnd(page);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`),
    context,
  ).toEqual([]);
}

async function openKb(page: Page, query = ""): Promise<void> {
  await spaGoto(page, `/crm/kb${query}`);
  await expect(page.getByRole("heading", { level: 1, name: "База знаний" })).toBeVisible();
}

function side(page: Page): Locator {
  return page.locator(PANEL);
}

function docRow(page: Page, title: string): Locator {
  return page
    .getByRole("row")
    .filter({ has: page.getByRole("link", { name: `Открыть документ: ${title}` }) });
}

test.describe("База знаний: администратор", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе; ширины проверяет блок axe");

  test("документы со статусом индексации словом; «Что найдёт бот» отвечает или говорит «не знаю»", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openKb(page);

    await expect(page.getByRole("heading", { level: 2, name: "Документы" })).toBeVisible();
    await expect(
      docRow(page, "Сроки и условия поставки").getByText("Готов", { exact: true }),
    ).toBeVisible();
    await expect(docRow(page, "Warranty and returns").getByText("Обрабатывается")).toBeVisible();
    await expect(docRow(page, "Прайс-лист (черновик)").getByText("Ошибка")).toBeVisible();
    await expect(docRow(page, "Устаревший регламент отгрузки").getByText("Выключен")).toBeVisible();
    await settledScreenshot(page, "documents");

    await page.getByLabel("Вопрос клиента").fill("Какие сроки поставки?");
    await page.getByRole("button", { name: "Найти" }).click();
    await expect(page.getByText("Бот ответит по базе знаний")).toBeVisible();
    await expect(page.getByText("Лучшее совпадение: 0.83, порог: 0.70")).toBeVisible();
    await settledScreenshot(page, "search-confident");

    await page.getByLabel("Вопрос клиента").fill("Расскажите про погоду");
    await page.getByRole("button", { name: "Найти" }).click();
    await expect(page.getByText("Бот скажет «не знаю» и предложит менеджера")).toBeVisible();
  });

  test("карточка документа: фрагменты, выключение и включение с «Что произойдёт», переиндексация", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openKb(page);

    await page.getByRole("link", { name: "Открыть документ: Сроки и условия поставки" }).click();
    const panel = side(page);
    await expect(
      panel.getByRole("heading", { level: 3, name: "Сроки и условия поставки" }),
    ).toBeVisible();
    await expect(panel.getByText("Фрагмент 1")).toBeVisible();
    await settledScreenshot(page, "document-card");

    await panel.getByRole("button", { name: "Выключить документ" }).click();
    const off = panel.getByRole("form", { name: "Выключить документ" });
    await expect(off.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    await settledScreenshot(page, "document-disable");
    await off.getByRole("button", { name: "Выключить документ" }).click();
    await expect(docRow(page, "Сроки и условия поставки").getByText("Выключен")).toBeVisible();

    await panel.getByRole("button", { name: "Включить документ" }).click();
    await panel
      .getByRole("form", { name: "Включить документ" })
      .getByRole("button", { name: "Включить документ" })
      .click();
    await expect(docRow(page, "Сроки и условия поставки").getByText("Выключен")).toHaveCount(0);

    await panel.getByRole("button", { name: "Переиндексировать" }).click();
    const again = panel.getByRole("form", { name: "Переиндексировать" });
    await expect(again.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    await again.getByRole("button", { name: "Переиндексировать документ" }).click();
    await expect(docRow(page, "Сроки и условия поставки").getByText("В очереди")).toBeVisible();
  });

  test("загрузка файла: ошибка формата словами, затем верный файл ставится в очередь", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openKb(page);

    await page.getByRole("link", { name: "Загрузить файл" }).click();
    const panel = side(page);
    const form = panel.getByRole("form", { name: "Загрузить файл Markdown" });
    await expect(form.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    await expect(form.getByRole("button", { name: "Загрузить документ" })).toBeDisabled();

    await form
      .getByLabel("Файл .md")
      .setInputFiles({ name: "price.pdf", mimeType: "application/pdf", buffer: Buffer.from("x") });
    await expect(form.getByRole("alert")).toContainText("Принимаются только файлы Markdown (.md).");

    await form.getByLabel("Файл .md").setInputFiles({
      name: "bad-format.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("# Без front matter\n"),
    });
    await form.getByRole("button", { name: "Загрузить документ" }).click();
    await expect(form.getByRole("alert")).toContainText("В начале файла нет front matter");
    await settledScreenshot(page, "upload-format-error");

    await form.getByLabel("Файл .md").setInputFiles({
      name: "garantiya.md",
      mimeType: "text/markdown",
      buffer: Buffer.from(
        "---\ntitle: Гарантия\nlanguage: ru\nsource: Договор\nupdated: 2026-10-26\n---\n# Гарантия\n",
      ),
    });
    await form.getByLabel("Название").fill("Гарантия на крепёж");
    await form.getByRole("button", { name: "Загрузить документ" }).click();
    await expect(page.getByText("Документ добавлен — индексация займёт до минуты")).toBeVisible();
    await expect(docRow(page, "Гарантия на крепёж").getByText("В очереди")).toBeVisible();
  });

  test("ручной ввод; подсказка по формату открывается спецификацией", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    await openKb(page);

    await page.getByRole("link", { name: "Загрузить файл" }).click();
    await side(page).getByText("Как подготовить файл").click();
    await side(page).getByRole("button", { name: "Полная спецификация" }).click();
    await expect(page.getByRole("dialog", { name: "Формат документа базы знаний" })).toBeVisible();
    await page.getByRole("button", { name: "Закрыть" }).click();

    await page.getByRole("link", { name: "Добавить вручную" }).click();
    const form = side(page).getByRole("form", { name: "Добавить документ вручную" });
    await form.getByLabel("Название").fill("Рассрочка платежа");
    await form
      .getByLabel("Текст документа (Markdown)")
      .fill("## Рассрочка\n\nПредоставляется по договору.");
    await form.getByRole("button", { name: "Добавить документ" }).click();
    await expect(docRow(page, "Рассрочка платежа").getByText("В очереди")).toBeVisible();
  });

  test("пробелы: создать документ из вопроса закрывает пробел; привязать, игнорировать, вернуть", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openKb(page, "?view=gaps");

    await expect(
      page.getByRole("heading", { level: 2, name: "Пробелы базы знаний" }),
    ).toBeVisible();
    await settledScreenshot(page, "gaps");
    await page.getByRole("link", { name: "Открыть пробел: Есть ли гарантия на крепёж?" }).click();
    const panel = side(page);
    await panel.getByRole("button", { name: "Создать документ из вопроса" }).click();
    const form = panel.getByRole("form", { name: "Добавить документ вручную" });
    await expect(form.getByLabel("Название")).toHaveValue("Есть ли гарантия на крепёж?");
    await settledScreenshot(page, "gap-create-document");
    await form
      .getByLabel("Текст документа (Markdown)")
      .fill("## Гарантия на крепёж\n\n12 месяцев.");
    await form.getByRole("button", { name: "Добавить документ" }).click();
    await expect(
      page.getByText("Документ добавлен, пробел закрыт — индексация займёт до минуты"),
    ).toBeVisible();

    await page.getByText("Пробелы", { exact: true }).click();
    await expect(
      page.getByRole("link", { name: "Открыть пробел: Есть ли гарантия на крепёж?" }),
    ).toHaveCount(0);

    await page.getByRole("link", { name: "Открыть пробел: Можно ли оплатить частями?" }).click();
    await panel.getByRole("button", { name: "Привязать к документу" }).click();
    const link = panel.getByRole("form", { name: "Привязать к документу" });
    await link.getByRole("combobox", { name: "Документ с ответом" }).click();
    await page.getByTitle("Гарантия на продукцию").click();
    await link.getByRole("button", { name: "Привязать и закрыть пробел" }).click();
    // exact: иначе совпадает ещё и тост «Документ добавлен, пробел закрыт — …» предыдущего шага, пока он не исчез (strict mode).
    await expect(page.getByText("Пробел закрыт", { exact: true })).toBeVisible();

    await page.getByRole("link", { name: "Открыть пробел: Do you deliver to Samarkand?" }).click();
    await panel.getByRole("button", { name: "Игнорировать" }).click();
    const ignore = panel.getByRole("form", { name: "Игнорировать" });
    await expect(ignore.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    await ignore.getByRole("button", { name: "Игнорировать пробел" }).click();
    await expect(page.getByText("Пробел скрыт")).toBeVisible();

    await page.getByText("Игнорируемые", { exact: true }).click();
    await page.getByRole("link", { name: "Открыть пробел: Do you deliver to Samarkand?" }).click();
    await panel.getByRole("button", { name: "Вернуть в открытые" }).click();
    await panel
      .getByRole("form", { name: "Вернуть в открытые" })
      .getByRole("button", { name: "Вернуть пробел" })
      .click();
    await expect(page.getByText("Пробел возвращён в открытые")).toBeVisible();
  });

  test("песочница: ответ бота с кнопками и «Почему так», передача менеджеру, сбой модели, «Начать заново»", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openKb(page, "?view=sandbox");

    await expect(page.getByRole("heading", { level: 2, name: "Песочница бота" })).toBeVisible();
    const input = page.getByLabel("Вопрос клиента");
    await input.fill("Какие сроки поставки рельсов?");
    await page.getByRole("button", { name: "Отправить боту" }).click();
    const log = page.getByRole("log", { name: "Диалог с ботом" });
    await expect(log.getByText(/Срок поставки рельсов — от 14 дней/)).toBeVisible();
    await expect(log.getByText("Передать менеджеру")).toBeVisible();
    await log.getByText("Почему бот ответил так").click();
    await expect(log.getByText("ответ по базе знаний")).toBeVisible();
    await settledScreenshot(page, "sandbox-answer");

    await input.fill("Сколько стоит доставка?");
    await page.getByRole("button", { name: "Отправить боту" }).click();
    await expect(log.getByText(/Передаю ваш вопрос менеджеру/)).toBeVisible();

    await input.fill("сбой модели");
    await page.getByRole("button", { name: "Отправить боту" }).click();
    await expect(
      page.getByText("Шлюз моделей не отвечает: бот не может сформировать ответ. Повторите позже."),
    ).toBeVisible();

    await page.getByRole("button", { name: "Начать заново" }).click();
    const reset = page.getByRole("form", { name: "Начать заново" });
    await expect(reset.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    await settledScreenshot(page, "sandbox-reset");
    await reset.getByRole("button", { name: "Очистить диалог" }).click();
    await expect(page.getByRole("log")).toHaveCount(0);
  });
});

test.describe("База знаний: права", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе; ширины проверяет блок axe");

  test("менеджер и директор читают базу знаний без кнопок изменения и без песочницы", async ({
    page,
  }) => {
    for (const email of ["manager@demo.example", "director@demo.example"]) {
      await loginAndWait(page, email);
      await openKb(page);
      await expect(page.getByText("Только просмотр", { exact: true })).toBeVisible();
      await expect(page.getByRole("link", { name: "Загрузить файл" })).toHaveCount(0);
      await expect(page.getByRole("radio", { name: "Песочница бота" })).toHaveCount(0);
      await page.getByRole("link", { name: "Открыть документ: Сроки и условия поставки" }).click();
      await expect(
        side(page).getByRole("heading", { level: 3, name: "Сроки и условия поставки" }),
      ).toBeVisible();
      await expect(side(page).getByRole("button", { name: "Выключить документ" })).toHaveCount(0);
      await page.evaluate("window.localStorage.clear()");
      await spaGoto(page, "/login");
    }
  });

  test("у снабженца пункта «База знаний» в меню CRM нет, прямой адрес — «Нет доступа»; у администратора пункт есть", async ({
    page,
  }) => {
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/crm/clients");
    await expect(page.getByRole("link", { name: "База знаний" })).toHaveCount(0);
    await spaGoto(page, "/crm/kb");
    await expect(page.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();

    await page.evaluate("window.localStorage.clear()");
    await spaGoto(page, "/login");
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/crm/kb");
    await expect(page.getByRole("link", { name: "База знаний" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 1, name: "База знаний" })).toBeVisible();
  });
});

test.describe("База знаний: axe и снимки", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`администратор на ${String(width)}: вкладки, карточки и формы без нарушений axe`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "admin@demo.example");

      await openKb(page);
      await expect(page.getByRole("heading", { level: 2, name: "Документы" })).toBeVisible();
      await expectNoViolations(page, `documents ${String(width)}`);
      await settledScreenshot(page, "a11y-documents");

      await openKb(page, "?doc=1&panel=open");
      await expect(side(page).getByText("Фрагмент 1")).toBeVisible();
      await expectNoViolations(page, `document card ${String(width)}`);
      await settledScreenshot(page, "a11y-document-card");
      await side(page).getByRole("button", { name: "Выключить документ" }).click();
      await expectNoViolations(page, `document disable form ${String(width)}`);

      await openKb(page, "?new=upload&panel=open");
      await expect(side(page).getByRole("form", { name: "Загрузить файл Markdown" })).toBeVisible();
      await expectNoViolations(page, `upload form ${String(width)}`);
      await settledScreenshot(page, "a11y-upload");
      await openKb(page, "?new=manual&panel=open");
      await expect(
        side(page).getByRole("form", { name: "Добавить документ вручную" }),
      ).toBeVisible();
      await expectNoViolations(page, `manual form ${String(width)}`);

      await openKb(page, "?view=gaps");
      await expect(
        page.getByRole("heading", { level: 2, name: "Пробелы базы знаний" }),
      ).toBeVisible();
      await expectNoViolations(page, `gaps ${String(width)}`);
      await settledScreenshot(page, "a11y-gaps");
      await openKb(page, "?view=gaps&gap=1&panel=open");
      await expect(
        side(page).getByRole("heading", { level: 3, name: "Есть ли гарантия на крепёж?" }),
      ).toBeVisible();
      await side(page).getByRole("button", { name: "Привязать к документу" }).click();
      await expectNoViolations(page, `gap card ${String(width)}`);
      await settledScreenshot(page, "a11y-gap-card");

      await openKb(page, "?view=sandbox");
      await expect(page.getByRole("heading", { level: 2, name: "Песочница бота" })).toBeVisible();
      await page.getByLabel("Вопрос клиента").fill("Какие сроки поставки?");
      await page.getByRole("button", { name: "Отправить боту" }).click();
      await expect(page.getByRole("log").getByText(/Срок поставки рельсов/)).toBeVisible();
      await expectNoViolations(page, `sandbox ${String(width)}`);
      await settledScreenshot(page, "a11y-sandbox");
    });

    test(`менеджер на ${String(width)}: просмотр без нарушений axe`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "manager@demo.example");
      await openKb(page);
      await expect(page.getByRole("heading", { level: 2, name: "Документы" })).toBeVisible();
      await expectNoViolations(page, `manager documents ${String(width)}`);
    });
  }
});
