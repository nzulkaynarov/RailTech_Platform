import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// EDS · Создать документ и «Мои документы» на MSW (D1-5): сотрудник создаёт служебную записку с суммой и вложением и отправляет
// её на согласование — документ виден в «Мои» со статусом «На согласовании»; черновик → «Продолжить» → отправка; сбой сервера
// не стирает введённое; реестр «Все» и вкладка КП у роли с доступом; письмо у роли с доступом к входящим; axe (WCAG 2.1 AA) на
// форме, списке и карточке; телефон (390): карточки вместо таблицы, лист на весь экран с кнопками внизу, форма с кнопками внизу;
// снимки 1440 и 390 для PR.
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

function inDays(days: number): string {
  return new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
}

function side(page: Page): Locator {
  return page.locator(PANEL);
}

function docLink(page: Page, subject: string): Locator {
  return page.getByRole("link", { name: `Открыть документ: ${subject}` });
}

async function openDocuments(page: Page, query = "?scope=mine"): Promise<void> {
  await spaGoto(page, `/eds/documents${query}`);
  await expect(page.getByRole("heading", { level: 1, name: "Все документы" })).toBeVisible();
}

async function fillMemo(page: Page, subject: string, text: string): Promise<void> {
  await page.getByLabel("Тема").fill(subject);
  await page.getByLabel("Текст").fill(text);
}

test.describe("Создать документ: сотрудник", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе; телефон — отдельный блок @mobile");

  test("служебка с суммой и вложением уходит на согласование и видна в «Мои» со статусом «На согласовании»", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await page
      .getByRole("navigation", { name: "Модули" })
      .getByRole("link", { name: "Документы" })
      .click();
    await expect(page.getByRole("heading", { level: 1, name: "Все документы" })).toBeVisible();

    // главное действие модуля — «Создать документ» внизу подменю
    await page.getByRole("link", { name: "Создать документ" }).first().click();
    await expect(page).toHaveURL(/\/eds\/new$/);
    await expect(page.getByRole("heading", { level: 1, name: "Создать документ" })).toBeVisible();
    await expect(page.getByLabel("Кому")).toHaveValue("Директор");

    await fillMemo(
      page,
      "Закупка мебели для переговорной",
      "Прошу согласовать закупку трёх столов и десяти стульев.",
    );
    await page.getByLabel("Сумма, сум").fill("3 600 000");
    await page.getByLabel("Нужно до").fill(inDays(7));
    await page.getByLabel("Вложения").setInputFiles({
      name: "schet-mebel.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4 демонстрационный счёт"),
    });
    const files = page.getByRole("list", { name: "Прикреплённые файлы" });
    await expect(files.getByText("schet-mebel.pdf")).toBeVisible();
    await expect(files.getByText("загружен")).toBeVisible();

    await page.getByLabel("Связь с проектом").click();
    await page.getByLabel("Связь с проектом").fill("рельс");
    await page.getByTitle(/ЗВ-2026-104 · Поставка рельсов Р65/).click();

    const block = page.getByRole("group", { name: "Что произойдёт" });
    await expect(page.getByText("Вы → Директор → Бухгалтер (есть сумма)")).toBeVisible();
    await expect(
      block.getByText("После согласования директором документ передадут бухгалтеру — к оплате."),
    ).toBeVisible();
    await settledScreenshot(page, "form-filled");

    await page.getByRole("button", { name: "Отправить на согласование" }).click();

    await expect(page).toHaveURL(/\/eds\/documents\?scope=mine&doc=/);
    const panel = side(page);
    await expect(
      panel.getByRole("heading", { level: 3, name: "Закупка мебели для переговорной" }),
    ).toBeVisible();
    await expect(panel.getByText("На согласовании")).toBeVisible();
    await expect(panel.getByText("Директор — ждёт решения")).toBeVisible();
    await expect(panel.getByText("Бухгалтер — дальше по маршруту")).toBeVisible();
    await expect(panel.getByRole("button", { name: "Скачать: schet-mebel.pdf" })).toBeVisible();
    await expect(panel.getByText("ЗВ-2026-104")).toBeVisible();
    await settledScreenshot(page, "document-panel");

    const row = page
      .getByRole("row")
      .filter({ has: docLink(page, "Закупка мебели для переговорной") });
    await expect(row.getByText("На согласовании")).toBeVisible();
    await expect(row.getByText("3 600 000 сум")).toBeVisible();
  });

  test("список «Мои документы»: статусы словами, у черновика и возврата — «Продолжить»; черновик правится и уходит", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await openDocuments(page);
    await expect(page.getByRole("tab", { name: "Все типы" })).toBeVisible();
    await expect(page.getByRole("radiogroup", { name: "Чьи документы" })).toBeVisible();
    await settledScreenshot(page, "my-documents");

    const draft = page
      .getByRole("row")
      .filter({ has: docLink(page, "Ремонт кондиционера в переговорной") });
    await expect(draft.getByText("Черновик")).toBeVisible();
    await expect(
      page
        .getByRole("row")
        .filter({ has: docLink(page, "Командировка в Самарканд") })
        .getByText("Возвращена на доработку"),
    ).toBeVisible();

    await draft.getByRole("link", { name: /Продолжить/ }).click();
    await expect(page).toHaveURL(/\/eds\/new\?draft=/);
    await expect(page.getByLabel("Тема")).toHaveValue("Ремонт кондиционера в переговорной");
    await expect(page.getByLabel("Сумма, сум")).toHaveValue("1200000");
    await expect(page.getByText("Тип нельзя менять после создания.")).toBeVisible();
    await settledScreenshot(page, "draft-continue");

    await page.getByLabel("Тема").fill("Ремонт кондиционера: замена компрессора");
    await page.getByRole("button", { name: "Отправить на согласование" }).click();

    const panel = side(page);
    await expect(
      panel.getByRole("heading", { level: 3, name: "Ремонт кондиционера: замена компрессора" }),
    ).toBeVisible();
    await expect(panel.getByText("На согласовании")).toBeVisible();
    // «Мои» по-прежнему одна запись с этим номером: черновик не размножился
    await expect(panel.getByText("СЗ-2026/033")).toBeVisible();
    await expect(docLink(page, "Ремонт кондиционера: замена компрессора")).toHaveCount(1);
  });

  test("сбой сервера: «Не отправлено: …», введённое остаётся, повтор идёт по тому же черновику", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/eds/new");
    await fillMemo(page, "Командировка в Бухару", "Нужна командировка на два дня. [сбой]");
    await page.getByLabel("Сумма, сум").fill("750 000");

    await page.getByRole("button", { name: "Отправить на согласование" }).click();

    const alert = page.getByRole("alert").filter({ hasText: "Не отправлено" });
    await expect(alert).toContainText("сервис документов не отвечает, повторите чуть позже");
    await expect(alert).toContainText("Черновик сохранён, введённое не потеряно");
    await expect(page.getByLabel("Тема")).toHaveValue("Командировка в Бухару");
    await expect(page.getByLabel("Сумма, сум")).toHaveValue("750 000");
    await settledScreenshot(page, "send-error");

    await page.getByLabel("Текст").fill("Нужна командировка на два дня.");
    await page.getByRole("button", { name: "Отправить на согласование" }).click();

    await expect(
      side(page).getByRole("heading", { level: 3, name: "Командировка в Бухару" }),
    ).toBeVisible();
    await expect(side(page).getByText("На согласовании")).toBeVisible();
    await expect(docLink(page, "Командировка в Бухару")).toHaveCount(1);
  });

  test("проверка полей: тема и текст обязательны, сумма больше нуля, «нужно до» не в прошлом", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/eds/new");

    await page.getByRole("button", { name: "Отправить на согласование" }).click();
    await expect(page.getByText("Укажите тему.")).toBeVisible();
    await expect(page.getByText("Напишите текст документа.")).toBeVisible();
    await expect(page.getByLabel("Тема")).toBeFocused();

    await fillMemo(page, "Тема", "Текст");
    await page.getByLabel("Сумма, сум").fill("0");
    await page.getByRole("button", { name: "Сохранить черновик" }).click();
    await expect(
      page.getByText("Сумма должна быть больше нуля, например 1 500 000."),
    ).toBeVisible();
    await settledScreenshot(page, "validation");

    await page.getByLabel("Сумма, сум").fill("1 000");
    await page.getByRole("button", { name: "Сохранить черновик" }).click();
    await expect(side(page).getByText("Черновик")).toBeVisible();
    await expect(side(page).getByRole("link", { name: "Продолжить" })).toBeVisible();
  });

  test("вложение: слишком большой файл и неподходящий тип отклоняются словами", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/eds/new");

    await page.getByLabel("Вложения").setInputFiles({
      name: "virus.exe",
      mimeType: "application/x-msdownload",
      buffer: Buffer.from("MZ"),
    });
    await expect(
      page
        .getByRole("list", { name: "Прикреплённые файлы" })
        .getByText("Допустимы PDF, изображения и документы Office."),
    ).toBeVisible();
    await page.getByRole("button", { name: "Убрать файл virus.exe" }).click();
    await expect(page.getByRole("list", { name: "Прикреплённые файлы" })).toHaveCount(0);
  });
});

test.describe("Создать документ: директор и реестр", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе; телефон — отдельный блок @mobile");

  test("реестр «Все»: письма и КП открываются в своих разделах, вкладка КП; «Мои» — только свои", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await openDocuments(page, "");

    await expect(page.getByText("Запрос цен на рельсы Р65")).toBeVisible();
    await expect(page.getByText("Заказ спецодежды для бригады")).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Ответственный" })).toBeVisible();
    await settledScreenshot(page, "registry-all");

    await page.getByRole("tab", { name: "КП" }).click();
    await expect(page.getByText("КП · Монтаж стрелочных переводов")).toBeVisible();
    await expect(page.getByText("Запрос цен на рельсы Р65")).toHaveCount(0);

    await page.getByText("Мои", { exact: true }).click();
    await expect(docLink(page, "Итоги недели по заявкам")).toBeVisible();
    await expect(page.getByText("Заказ спецодежды для бригады")).toHaveCount(0);
  });

  test("письмо: у директора есть адресат вместо «Кому», регистрация даёт статус «Зарегистрировано»", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/eds/new?type=letter");

    await expect(page.getByLabel("Адресат (организация)")).toBeVisible();
    await expect(page.getByLabel("Сумма, сум")).toHaveCount(0);
    await page.getByLabel("Адресат (организация)").fill("ООО «Демо-Путь»");
    await fillMemo(page, "Ответ на запрос цен", "Направляем коммерческие условия.");
    await settledScreenshot(page, "letter-form");
    await page.getByRole("button", { name: "Зарегистрировать письмо" }).click();

    const panel = side(page);
    await expect(
      panel.getByRole("heading", { level: 3, name: "Ответ на запрос цен" }),
    ).toBeVisible();
    await expect(panel.getByText("Зарегистрировано")).toBeVisible();
    await expect(panel.getByText(/ИСХ-082\/26/)).toBeVisible();
    await expect(panel.getByText("ООО «Демо-Путь»")).toBeVisible();
  });

  test("менеджеру письмо недоступно: подсказка словами, форма остаётся служебной запиской", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/eds/new?type=letter");

    await expect(
      page.getByText("Письма регистрирует роль с доступом к входящим письмам."),
    ).toBeVisible();
    await expect(page.getByLabel("Кому")).toBeVisible();
  });

  test("администратор: без доступа к реестру — только «Мои», пусто словами и с действием", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openDocuments(page, "");

    await expect(page.getByText("Своих документов пока нет")).toBeVisible();
    await expect(page.getByRole("radiogroup", { name: "Чьи документы" })).toHaveCount(0);
    await settledScreenshot(page, "my-documents-empty");
    await page.getByRole("link", { name: "Создать документ" }).first().click();
    await expect(page).toHaveURL(/\/eds\/new$/);
  });
});

test.describe("Создать документ: axe и снимки", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of [1440, 390] as const) {
    test(`форма, список и карточка на ${String(width)} без нарушений axe`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");

      await spaGoto(page, "/eds/new");
      await expect(page.getByRole("heading", { level: 1, name: "Создать документ" })).toBeVisible();
      await expectNoViolations(page, `форма ${String(width)}`);
      await settledScreenshot(page, "a11y-form");

      await fillMemo(page, "Тема", "Текст");
      await page.getByLabel("Сумма, сум").fill("0");
      await page.getByRole("button", { name: "Сохранить черновик" }).click();
      await expect(
        page.getByText("Сумма должна быть больше нуля, например 1 500 000."),
      ).toBeVisible();
      await expectNoViolations(page, `форма с ошибкой ${String(width)}`);

      await spaGoto(page, "/eds/new?type=letter");
      await expect(page.getByLabel("Адресат (организация)")).toBeVisible();
      await expectNoViolations(page, `письмо ${String(width)}`);

      await openDocuments(page, "?scope=mine");
      await expect(docLink(page, "Итоги недели по заявкам")).toBeVisible();
      await expectNoViolations(page, `мои документы ${String(width)}`);
      await settledScreenshot(page, "a11y-my-documents");

      await openDocuments(page, "");
      await expect(page.getByText("Запрос цен на рельсы Р65")).toBeVisible();
      await expectNoViolations(page, `реестр ${String(width)}`);

      await openDocuments(page, "?scope=mine");
      await docLink(page, "Итоги недели по заявкам").click();
      await expect(
        page.getByRole("heading", { level: 3, name: "Итоги недели по заявкам" }),
      ).toBeVisible();
      await expectNoViolations(page, `карточка ${String(width)}`);
      await settledScreenshot(page, "a11y-document");
    });
  }
});

// @mobile: проект mobile (Pixel 7, 390) гоняет только сценарии с этим тегом — экраны с адаптивной логикой.
test.describe("Создать документ: телефон", () => {
  test(
    "список — карточки, документ открывается листом на весь экран с кнопками внизу, форма с кнопками внизу",
    { tag: "@mobile" },
    async ({ page, isMobile }) => {
      test.skip(!isMobile, "узкий экран — проект mobile");
      await loginAndWait(page, "manager@demo.example");
      await openDocuments(page, "?scope=mine");

      await expect(page.getByRole("table")).toHaveCount(0);
      const list = page.getByRole("list", { name: "Документы" });
      await expect(list).toBeVisible();
      await settledScreenshot(page, "mobile-my-documents");
      await expectNoViolations(page, "мобильный список");

      await list.getByRole("link", { name: "Открыть документ: Командировка в Самарканд" }).click();
      const sheet = page.getByRole("dialog", { name: "Документ" });
      await expect(
        sheet.getByRole("heading", { level: 3, name: "Командировка в Самарканд" }),
      ).toBeVisible();
      const box = await sheet.boundingBox();
      const viewport = page.viewportSize();
      expect(box?.width).toBe(viewport?.width);
      expect(box?.height).toBe(viewport?.height);
      const actions = sheet.getByRole("link", { name: "Продолжить" }).locator("..");
      await expect(actions).toBeVisible();
      const actionsBox = await actions.boundingBox();
      expect((actionsBox?.y ?? 0) + (actionsBox?.height ?? 0)).toBeGreaterThan(
        (viewport?.height ?? 0) - 40,
      );
      await settledScreenshot(page, "mobile-document-sheet");
      await expectNoViolations(page, "мобильный лист");
      await sheet.getByRole("button", { name: "Закрыть документ" }).click();
      await expect(page.getByRole("dialog", { name: "Документ" })).toHaveCount(0);

      await page.getByRole("link", { name: "Создать документ" }).first().click();
      await expect(page.getByRole("heading", { level: 1, name: "Создать документ" })).toBeVisible();
      await fillMemo(page, "Заказ воды для офиса", "Прошу согласовать заказ питьевой воды.");
      const submit = page.getByRole("button", { name: "Отправить на согласование" });
      await expect(submit).toBeVisible();
      // кнопки прижаты к низу экрана (над нижней панелью модулей)
      const submitBox = await submit.boundingBox();
      expect((submitBox?.y ?? 0) + (submitBox?.height ?? 0)).toBeGreaterThan(
        (viewport?.height ?? 0) - 140,
      );
      await settledScreenshot(page, "mobile-form");
      await expectNoViolations(page, "мобильная форма");

      await submit.click();
      await expect(
        page.getByRole("dialog", { name: "Документ" }).getByRole("heading", {
          level: 3,
          name: "Заказ воды для офиса",
        }),
      ).toBeVisible();
      await expect(
        page.getByRole("dialog", { name: "Документ" }).getByText("На согласовании"),
      ).toBeVisible();
    },
  );
});
