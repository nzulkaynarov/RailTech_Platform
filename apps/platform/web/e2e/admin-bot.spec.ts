import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// Admin · Настройки бота на MSW (W13-A5): разделы настроек по схемам CRM (сохранение, отмена, ошибка поля, защита от потери
// изменений), тексты бота в боковом окне, пробный прогон правил передачи, шаблоны ответов (создать, изменить, удалить),
// выгрузки CSV (скачивание файла с датой в имени); директор читает без кнопок изменения; axe (WCAG 2.1 AA) на всех разделах;
// снимки 1440 и 390 для PR.
const WIDTHS = [1440, 390] as const;
const PANEL = "#pf-context-panel";
const SECTIONS = [
  "company",
  "business_hours",
  "texts",
  "bot",
  "kb",
  "stop_words",
  "competitors",
  "escalation",
  "qualification",
  "web_form",
  "notifications",
  "service_alerts",
  "deals",
  "budget",
  "templates",
  "exports",
] as const;

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

async function openBot(page: Page, section?: string, extra = ""): Promise<void> {
  const query = [section ? `section=${section}` : "", extra].filter(Boolean).join("&");
  await spaGoto(page, `/admin/bot${query ? `?${query}` : ""}`);
  await expect(page.getByRole("heading", { level: 1, name: "Telegram-бот" })).toBeVisible();
  await expect(page.locator(".ant-skeleton")).toHaveCount(0);
}

function side(page: Page): Locator {
  return page.locator(PANEL);
}

function nav(page: Page): Locator {
  return page.getByRole("navigation", { name: "Разделы настроек бота" });
}

test.describe("Настройки бота: администратор", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе; ширины проверяет блок axe");

  test("разделы по группам; «Компания»: изменить, отменить, сохранить с «Что произойдёт»", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openBot(page);

    await expect(page.getByRole("heading", { level: 2, name: "Компания" })).toBeVisible();
    await expect(nav(page).getByRole("link")).toHaveCount(16);
    await expect(page.getByLabel("Название компании")).toHaveValue("RailTech (демо)");
    await expect(page.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    await settledScreenshot(page, "company");

    await page.getByLabel("Название компании").fill("RailTech Групп (демо)");
    await expect(page.getByText("Есть несохранённые изменения")).toBeVisible();
    await page.getByRole("button", { name: "Отменить изменения" }).click();
    await expect(page.getByLabel("Название компании")).toHaveValue("RailTech (демо)");

    await page.getByLabel("Название компании").fill("RailTech Групп (демо)");
    await page.getByRole("button", { name: "Сохранить" }).click();
    await expect(page.getByText("Настройки «Компания» сохранены")).toBeVisible();
    await expect(page.getByText("Изменений нет")).toBeVisible();
    await settledScreenshot(page, "company-saved");
  });

  test("поле, которое CRM не приняла, подсвечивается; несохранённые изменения при смене раздела", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openBot(page);

    await page.getByLabel("Название компании").fill("   ");
    await page.getByRole("button", { name: "Сохранить" }).click();
    await expect(
      page.getByText("CRM не приняла значения: проверьте отмеченные поля."),
    ).toBeVisible();
    await settledScreenshot(page, "company-error");

    await nav(page).getByRole("link", { name: "Рабочие часы" }).click();
    const dialog = page.getByRole("dialog", { name: "Выйти без сохранения?" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Остаться" }).click();
    await expect(page.getByLabel("Название компании")).toHaveValue("   ");
    await nav(page).getByRole("link", { name: "Рабочие часы" }).click();
    await page
      .getByRole("dialog", { name: "Выйти без сохранения?" })
      .getByRole("button", { name: "Выйти без сохранения" })
      .click();
    await expect(page.getByRole("heading", { level: 2, name: "Рабочие часы" })).toBeVisible();
  });

  test("рабочие часы, поведение бота, квалификация, бюджет: поля подписаны, значения сохраняются", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");

    await openBot(page, "business_hours");
    await expect(page.getByLabel("Начало рабочего дня")).toHaveValue("09:00");
    const saturday = page
      .getByRole("group", { name: "Рабочие дни" })
      .getByRole("checkbox", { name: "Сб" });
    await saturday.click();
    await expect(saturday).toBeChecked();
    await page.getByRole("button", { name: "Сохранить" }).click();
    await expect(page.getByText("Настройки «Рабочие часы» сохранены")).toBeVisible();
    await settledScreenshot(page, "business-hours");

    await openBot(page, "bot");
    await page.getByLabel("Максимум слов в ответе").fill("80");
    await page.getByRole("button", { name: "Сохранить" }).click();
    await expect(page.getByText("Настройки «Поведение бота» сохранены")).toBeVisible();

    await openBot(page, "qualification");
    await expect(page.getByText("Лид становится «Квалифицирован»")).toBeVisible();
    await settledScreenshot(page, "qualification");

    await openBot(page, "budget");
    await expect(
      page.getByText("Anthropic (диалог, квалификатор, проверка качества)"),
    ).toBeVisible();
    await openBot(page, "notifications");
    await expect(page.getByRole("link", { name: "Открыть Telegram" })).toBeVisible();
  });

  test("тексты бота: таблица по группам, поиск, правка в боковом окне с предпросмотром, пустой перевод отклоняется", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openBot(page, "texts");

    await expect(page.getByText(/Приветствие и согласие · /)).toBeVisible();
    await settledScreenshot(page, "texts");
    await page
      .getByRole("searchbox", { name: "Найти текст по названию или ситуации" })
      .fill("нерабочее");
    await expect(page.getByText("Передача менеджеру (нерабочее время)")).toBeVisible();
    await page.getByRole("searchbox", { name: "Найти текст по названию или ситуации" }).fill("");

    await page.getByRole("button", { name: "Изменить: Приветствие" }).click();
    const panel = side(page);
    await expect(panel.getByRole("heading", { level: 3, name: "Приветствие" })).toBeVisible();
    await panel
      .getByLabel("Приветствие · Русский")
      .fill("Здравствуйте! Вас приветствует {company}.");
    await expect(
      panel.getByText(/Предпросмотр: Здравствуйте! Вас приветствует RailTech \(демо\)\./),
    ).toBeVisible();
    await settledScreenshot(page, "texts-edit");

    await panel.getByLabel("Приветствие · Узбекский").fill("");
    await panel.getByRole("button", { name: "Сохранить раздел" }).click();
    await expect(panel.getByText("Нет перевода").first()).toBeVisible();
    await panel.getByLabel("Приветствие · Узбекский").fill("Salom! {company} sizni qutlaydi.");
    await panel.getByRole("button", { name: "Сохранить раздел" }).click();
    await expect(page.getByText("Настройки «Тексты бота» сохранены")).toBeVisible();
  });

  test("правила передачи: пробный прогон на значениях из формы ничего не сохраняет", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openBot(page, "escalation");

    const dry = page.getByRole("region", { name: "Пробный прогон правил передачи" });
    await expect(dry.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    await dry.getByRole("button", { name: "Проверить на последних 50 диалогах" }).click();
    await expect(dry.getByRole("status", { name: "Итог пробного прогона" })).toContainText(
      "Изменится: 0",
    );

    await page.getByLabel("Оценка лида для передачи").fill("55");
    await dry.getByRole("button", { name: "Проверить на последних 50 диалогах" }).click();
    await expect(dry.getByText("Изменится у лидов: 2")).toBeVisible();
    await expect(dry.getByRole("status", { name: "Итог пробного прогона" })).toContainText(
      "Передач с новыми правилами",
    );
    await settledScreenshot(page, "escalation-dry-run");
    await expect(page.getByText("Есть несохранённые изменения")).toBeVisible();
  });

  test("шаблоны ответов: создать, изменить, удалить с «Что произойдёт»", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    await openBot(page, "templates");

    await expect(
      page.getByRole("link", { name: "Открыть шаблон: Пришлю КП сегодня" }),
    ).toBeVisible();
    await settledScreenshot(page, "templates");
    await page.getByRole("link", { name: "Новый шаблон" }).click();
    const form = side(page).getByRole("form", { name: "Новый шаблон" });
    await expect(form.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    await form.getByLabel("Название").fill("Скидка по запросу");
    await form.getByLabel("Текст — Русский").fill("{name}, скидку согласует {manager}.");
    await settledScreenshot(page, "templates-new");
    await form.getByRole("button", { name: "Создать шаблон" }).click();
    await expect(page.getByText("Шаблон создан")).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Открыть шаблон: Скидка по запросу" }),
    ).toBeVisible();

    const edit = side(page).getByRole("form", { name: "Изменить шаблон" });
    await edit.getByLabel("Название").fill("Скидка по согласованию");
    await edit.getByRole("button", { name: "Сохранить шаблон" }).click();
    await expect(page.getByText("Шаблон сохранён")).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Открыть шаблон: Скидка по согласованию" }),
    ).toBeVisible();

    await side(page).getByRole("button", { name: "Удалить шаблон" }).click();
    const remove = side(page).getByRole("form", { name: "Удалить шаблон" });
    await expect(remove.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    await settledScreenshot(page, "templates-delete");
    await remove.getByRole("button", { name: "Удалить шаблон" }).click();
    await expect(page.getByText("Шаблон удалён")).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Открыть шаблон: Скидка по согласованию" }),
    ).toHaveCount(0);

    await side(page)
      .getByRole("button", { name: /Закрыть|Скрыть/ })
      .first()
      .click()
      .catch(() => undefined);
    await page.getByRole("link", { name: "Новый шаблон" }).click();
    const bad = side(page).getByRole("form", { name: "Новый шаблон" });
    await bad.getByLabel("Название").fill("Ошибка");
    await bad.getByLabel("Текст — Русский").fill("Привет, {fio}");
    await bad.getByRole("button", { name: "Создать шаблон" }).click();
    await expect(bad.getByRole("alert")).toContainText("CRM не приняла значения");
  });
});

test.describe("Настройки бота: выгрузки CSV", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе; ширины проверяет блок axe");

  test("администратор без второй роли: кнопки недоступны и объяснены; с ролями данных — файл скачивается с датой в имени", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openBot(page, "exports");
    await expect(page.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    for (const title of ["Лиды", "Клиенты", "Сделки"]) {
      await expect(page.getByRole("button", { name: `Скачать: ${title}` })).toBeDisabled();
    }
    await expect(page.getByText(/нужен раздел «Клиенты · Лиды»/)).toBeVisible();
    await settledScreenshot(page, "exports-admin-only");

    await page.evaluate("window.localStorage.clear()");
    await spaGoto(page, "/login");
    await loginAndWait(page, "all@demo.example");
    await openBot(page, "exports");
    const leads = page.locator('article[data-entity="leads"]');
    await leads.getByLabel("Язык").click();
    await page.getByTitle("Узбекский").click();
    const download = page.waitForEvent("download");
    await leads.getByRole("button", { name: "Скачать: Лиды" }).click();
    expect((await download).suggestedFilename()).toBe("leads-20261026-1430.csv");
    await expect(page.getByText("Файл «leads-20261026-1430.csv» скачан")).toBeVisible();
    await settledScreenshot(page, "exports");

    const deals = page.locator('article[data-entity="deals"]');
    const second = page.waitForEvent("download");
    await deals.getByRole("button", { name: "Скачать: Сделки" }).click();
    expect((await second).suggestedFilename()).toBe("deals-20261026-1430.csv");
  });
});

test.describe("Настройки бота: права", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе; ширины проверяет блок axe");

  test("директор читает разделы, шаблоны и выгрузки без кнопок изменения", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await openBot(page);

    await expect(page.getByText("Только просмотр").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Сохранить" })).toHaveCount(0);
    await expect(page.getByLabel("Название компании")).toBeDisabled();
    await openBot(page, "escalation");
    await expect(
      page.getByRole("button", { name: "Проверить на последних 50 диалогах" }),
    ).toHaveCount(0);
    await openBot(page, "templates");
    await expect(page.getByRole("link", { name: "Новый шаблон" })).toHaveCount(0);
    await expect(
      page.getByRole("link", { name: "Открыть шаблон: Пришлю КП сегодня" }),
    ).toBeVisible();
    await openBot(page, "exports");
    await expect(page.getByRole("button", { name: "Скачать: Лиды" })).toBeDisabled();
    await settledScreenshot(page, "director-view");
  });

  test("менеджер: пункта «Настройки бота» нет, прямой адрес — «Нет доступа»; в Admin у директора пункт есть", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/admin/bot");
    await expect(page.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Telegram-бот" })).toHaveCount(0);

    await page.evaluate("window.localStorage.clear()");
    await spaGoto(page, "/login");
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/admin/roles");
    await expect(page.getByRole("link", { name: "Telegram-бот" })).toBeVisible();
  });
});

test.describe("Настройки бота: axe и снимки", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`администратор на ${String(width)}: все разделы, панели и формы без нарушений axe`, async ({
      page,
    }) => {
      test.setTimeout(240_000);
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "admin@demo.example");

      for (const section of SECTIONS) {
        await openBot(page, section);
        await expect(page.locator("h2").first()).toBeVisible();
        await expectNoViolations(page, `${section} ${String(width)}`);
        if (
          ["company", "business_hours", "texts", "escalation", "templates", "exports"].includes(
            section,
          )
        ) {
          await settledScreenshot(page, `a11y-${section}`);
        }
      }

      await openBot(page, "texts", "text=greeting&panel=open");
      await expect(
        side(page).getByRole("heading", { level: 3, name: "Приветствие" }),
      ).toBeVisible();
      await expectNoViolations(page, `text editor ${String(width)}`);
      await settledScreenshot(page, "a11y-text-editor");

      await openBot(page, "templates", "template=1&panel=open");
      await expect(side(page).getByRole("form", { name: "Изменить шаблон" })).toBeVisible();
      await side(page).getByRole("button", { name: "Удалить шаблон" }).click();
      await expectNoViolations(page, `template form ${String(width)}`);
      await settledScreenshot(page, "a11y-template-form");

      await openBot(page, "escalation");
      await page.getByRole("button", { name: "Проверить на последних 50 диалогах" }).click();
      await expect(page.getByRole("status", { name: "Итог пробного прогона" })).toBeVisible();
      await expectNoViolations(page, `dry run ${String(width)}`);
    });

    test(`директор на ${String(width)}: просмотр без нарушений axe`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      for (const section of ["company", "texts", "templates", "exports"]) {
        await openBot(page, section);
        await expectNoViolations(page, `director ${section} ${String(width)}`);
      }
    });
  }
});
