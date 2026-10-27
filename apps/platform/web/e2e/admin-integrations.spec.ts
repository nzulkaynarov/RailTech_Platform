import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// Admin · Внешние интеграции на MSW (W13-A1): каждое действие экрана — проверка связи, сопряжение и ротация ERP, токен бота и
// канал команды, SMTP и тестовое письмо, выключатель сервиса, смена и сброс модели, копия вне расписания; директор читает
// без кнопок изменения; axe (WCAG 2.1 AA) на обзоре и на всех карточках; снимки 1440 и 390 для PR.
const WIDTHS = [1440, 390] as const;
const PANEL = "#pf-context-panel";
const PASSWORD = "demo-pass-1";
const WRONG_PASSWORD = "wrong-password";
const CARDS = [
  "erp",
  "telegram",
  "mail",
  "services",
  "models",
  "spend",
  "storage",
  "system",
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

async function openIntegrations(page: Page, card?: string): Promise<void> {
  await spaGoto(page, card ? `/admin/integrations?card=${card}&panel=open` : "/admin/integrations");
  await expect(page.getByRole("heading", { level: 1, name: "Внешние интеграции" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Сервисы" })).toBeVisible();
}

function side(page: Page): Locator {
  return page.locator(PANEL);
}

function tile(page: Page, key: string): Locator {
  return page.locator(`article[data-card="${key}"]`);
}

async function password(form: Locator, value = PASSWORD): Promise<void> {
  await form.getByLabel("Ваш пароль администратора").fill(value);
}

/** Скриншот высокого окна: блок «Что произойдёт» и форма лежат ниже первого экрана панели. */
async function tallScreenshot(page: Page, name: string): Promise<void> {
  const width = page.viewportSize()?.width ?? 1440;
  await page.setViewportSize({ width, height: 1500 });
  await settledScreenshot(page, name);
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
}

test.describe("Внешние интеграции: администратор", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе; ширины проверяет блок axe");

  test("обзор: «Требует внимания» вверху, карточки со статусом словом; «Проверить» чинит почту", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openIntegrations(page);

    const attention = page
      .getByRole("heading", { level: 2, name: "Требует внимания" })
      .locator("xpath=ancestor::section[1]");
    await expect(attention.getByText(/Ключ OpenAI отклонён/)).toBeVisible();
    await expect(attention.getByText("В очереди 3 письма дольше 15 минут")).toBeVisible();
    await expect(tile(page, "erp").getByText("Работает", { exact: true })).toBeVisible();
    await expect(tile(page, "mail").getByText("Внимание", { exact: true })).toBeVisible();
    await expect(tile(page, "models").getByText("Сбой", { exact: true })).toBeVisible();
    await settledScreenshot(page, "overview");

    await tile(page, "mail").getByRole("button", { name: "Проверить: Почта" }).click();
    await expect(tile(page, "mail").getByText("Проверено: Работает")).toBeVisible();
    await expect(attention.getByText("В очереди 3 письма дольше 15 минут")).toHaveCount(0);
    await settledScreenshot(page, "overview-after-check");
  });

  test("ERP: проверка связи, подключение (неверный пароль, код), ротация ключа с «Что произойдёт»", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openIntegrations(page);
    await tile(page, "erp").getByRole("link", { name: "Открыть: ERP" }).click();
    const panel = side(page);
    await expect(panel.getByText("Сопряжена")).toBeVisible();
    await expect(panel.getByText("•••• 9f3c")).toBeVisible();
    await settledScreenshot(page, "erp-panel");

    await panel.getByRole("button", { name: "Проверить связь" }).click();
    await expect(panel.getByText("ERP отвечает", { exact: true })).toBeVisible();

    await panel.getByRole("button", { name: "Подключить заново" }).click();
    const pair = panel.getByRole("form", { name: "Подключить ERP" });
    await expect(pair.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    await password(pair, WRONG_PASSWORD);
    await pair.getByRole("button", { name: "Подключить ERP" }).click();
    await expect(pair.getByRole("alert")).toContainText("Пароль указан неверно.");
    await pair.getByLabel("Одноразовый код сопряжения").fill("000000");
    await password(pair);
    await pair.getByRole("button", { name: "Подключить ERP" }).click();
    await expect(pair.getByRole("alert")).toContainText("Код сопряжения не подошёл.");
    await tallScreenshot(page, "erp-pair-error");
    await pair.getByLabel("Одноразовый код сопряжения").fill("428193");
    await pair.getByRole("button", { name: "Подключить ERP" }).click();
    await expect(panel.getByText("Сопряжение выполнено.")).toBeVisible();
    await expect(panel.getByText("•••• 5a1d")).toBeVisible();

    await panel.getByRole("button", { name: "Подключить заново" }).click();
    await panel.getByRole("button", { name: "Ротация ключа" }).click();
    const rotate = panel.getByRole("form", { name: "Ротация ключей ERP" });
    await expect(rotate.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    await tallScreenshot(page, "erp-rotate");
    await password(rotate);
    await rotate.getByRole("button", { name: "Обновить ключи" }).click();
    await expect(panel.getByText("Ключи обновлены.")).toBeVisible();
    await expect(tile(page, "erp").getByText("Идёт переход на новые ключи")).toBeVisible();
  });

  test("Telegram: токен (маска, ошибка), канал команды, тестовое сообщение, профиль бота", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openIntegrations(page, "telegram");
    const panel = side(page);
    await expect(panel.getByText("@demo_railtech_bot")).toBeVisible();
    await expect(panel.getByText("•••• Qw7x")).toBeVisible();

    await panel.getByRole("button", { name: "Сменить токен" }).click();
    const form = panel.getByRole("form", { name: "Токен бота" });
    await expect(form.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    await form.getByLabel("Токен бота", { exact: true }).fill("bad-0000000000000000000000");
    await password(form);
    await form.getByRole("button", { name: "Сохранить токен" }).click();
    await expect(form.getByRole("alert")).toContainText("Telegram не принял токен");
    await tallScreenshot(page, "telegram-token");
    await form
      .getByLabel("Токен бота", { exact: true })
      .fill("100200:demoTokenValue000000000000Mn4k");
    await form.getByRole("button", { name: "Сохранить токен" }).click();
    await expect(panel.getByText("•••• Mn4k")).toBeVisible();
    await expect(page.locator("body")).not.toContainText("demoTokenValue");

    await panel.getByRole("button", { name: "Подключить канал: Склад и логистика (демо)" }).click();
    await expect(panel.getByText("Подключён: Склад и логистика (демо)")).toBeVisible();
    await panel.getByRole("button", { name: "Тестовое сообщение" }).click();
    await expect(page.getByText("Тестовое сообщение отправлено в канал")).toBeVisible();

    await panel.getByLabel("Имя бота").fill("RailTech Бот");
    await panel.getByRole("button", { name: "Сохранить и опубликовать" }).click();
    await expect(page.getByText("Профиль бота сохранён")).toBeVisible();
  });

  test("Почта: проверка, тестовое письмо в журнале, настройки SMTP", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    await openIntegrations(page, "mail");
    const panel = side(page);
    await expect(panel.getByText("smtp.demo.example:587")).toBeVisible();
    await expect(panel.getByText("•••• k3Zp")).toBeVisible();
    await settledScreenshot(page, "mail-panel");

    await panel.getByRole("button", { name: "Проверить связь" }).click();
    await expect(panel.getByText("Сервер принял соединение и вход")).toBeVisible();
    await panel.getByRole("button", { name: "Тестовое письмо" }).click();
    const log = panel.getByRole("list", { name: "Журнал отправок" });
    await expect(log.getByText("Тестовое письмо")).toBeVisible();

    await panel.getByRole("button", { name: "Настроить SMTP" }).click();
    const form = panel.getByRole("form", { name: "Настройки SMTP" });
    await form.getByLabel("Сервер (хост)").fill("bad host");
    await password(form);
    await form.getByRole("button", { name: "Сохранить настройки" }).click();
    await expect(form.getByRole("alert")).toContainText("Сервер почты указан неверно.");
    await form.getByLabel("Сервер (хост)").fill("smtp2.demo.example");
    await form.getByLabel("Пароль SMTP").fill("fresh-smtp-secret-p4ss");
    await tallScreenshot(page, "mail-settings");
    await form.getByRole("button", { name: "Сохранить настройки" }).click();
    await expect(panel.getByText("smtp2.demo.example:587")).toBeVisible();
    await expect(panel.getByText("•••• p4ss")).toBeVisible();
    await expect(page.locator("body")).not.toContainText("fresh-smtp-secret");
  });

  test("Внешние сервисы: проверка, выключатель с «Что произойдёт» и паролем, включение", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openIntegrations(page, "services");
    const panel = side(page);
    await expect(panel.getByText("Telegram Bot API")).toBeVisible();
    await settledScreenshot(page, "services-panel");

    await panel.getByRole("button", { name: "Проверить сервис: Почтовый релей (SMTP)" }).click();
    await expect(panel.getByText(/В очереди 3 письма/)).toHaveCount(0);

    await panel.getByRole("button", { name: "Выключить сервис: Telegram Bot API" }).click();
    const form = panel.getByRole("form", { name: "Выключить сервис: Telegram Bot API" });
    await expect(
      form.getByRole("group", { name: "Что произойдёт" }).getByText(/Бот перестанет отвечать/),
    ).toBeVisible();
    await form.getByLabel("Причина (попадёт в журнал)").fill("профилактика");
    await tallScreenshot(page, "services-disable");
    await password(form);
    await form.getByRole("button", { name: "Выключить сервис" }).click();
    await expect(panel.getByText("выключено вручную")).toBeVisible();

    await panel.getByRole("button", { name: "Включить сервис: Telegram Bot API" }).click();
    const enable = panel.getByRole("form", { name: "Включить сервис: Telegram Bot API" });
    await password(enable);
    await enable.getByRole("button", { name: "Включить сервис" }).click();
    await expect(panel.getByText("выключено вручную")).toHaveCount(0);
  });

  test("Модели ИИ: проверка, смена с ключом, сброс; ключ на экране не появляется", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openIntegrations(page, "models");
    const panel = side(page);
    await expect(panel.getByText("Поиск по базе знаний", { exact: true })).toBeVisible();
    await settledScreenshot(page, "models-panel");

    await panel.getByRole("button", { name: "Проверить модель: Поиск по базе знаний" }).click();
    const confirm = panel.getByRole("form", { name: "Проверка модели «Поиск по базе знаний»" });
    await expect(confirm.getByRole("group", { name: "Что произойдёт" })).toContainText(
      "платный запрос",
    );
    await confirm.getByRole("button", { name: "Проверить модель" }).click();
    await expect(panel.getByText("Модель «Поиск по базе знаний» не ответила")).toBeVisible();

    await panel.getByRole("button", { name: "Сменить модель: Поиск по базе знаний" }).click();
    const form = panel.getByRole("form", { name: "Сменить модель: Поиск по базе знаний" });
    await form.getByLabel("Ключ провайдера").fill("demo-provider-key-91zx");
    await tallScreenshot(page, "models-change");
    await password(form);
    await form.getByRole("button", { name: "Сменить модель" }).click();
    await expect(panel.getByText(/Модель сменена: openai/)).toBeVisible();
    await expect(page.locator("body")).not.toContainText("demo-provider-key-91zx");

    await panel.getByRole("button", { name: "Сбросить модель: Диалог с клиентом" }).click();
    const reset = panel.getByRole("form", { name: "Сбросить модель: Диалог с клиентом" });
    await expect(reset.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    await password(reset);
    await reset.getByRole("button", { name: "Сбросить к значению по умолчанию" }).click();
    await expect(panel.getByText("Используется ключ из настроек сервера.")).toBeVisible();
  });

  test("Расходы, хранилище и бэкапы, состояние системы", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    await openIntegrations(page, "spend");
    const panel = side(page);
    await expect(panel.getByRole("table", { name: "Провайдеры за сегодня" })).toBeVisible();
    await expect(panel.getByRole("table", { name: "Расходы по группам" })).toBeVisible();
    await tallScreenshot(page, "spend-panel");

    await openIntegrations(page, "storage");
    await expect(panel.getByText("crm-2026-10-26.dump")).toBeVisible();
    await panel.getByRole("button", { name: "Сделать копию сейчас" }).click();
    await expect(
      panel
        .getByRole("form", { name: "Копия вне расписания" })
        .getByRole("group", { name: "Что произойдёт" }),
    ).toBeVisible();
    await tallScreenshot(page, "storage-request");
    await panel.getByRole("button", { name: "Запросить копию" }).click();
    await expect(panel.getByText(/Копия по запросу ожидает сервис бэкапа/)).toBeVisible();

    await openIntegrations(page, "system");
    await expect(panel.getByRole("list", { name: "Состояние системы" })).toBeVisible();
    await expect(panel.getByText("Очередь задач")).toBeVisible();
    await settledScreenshot(page, "system-panel");
  });
});

test.describe("Внешние интеграции: директор и права", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе; ширины проверяет блок axe");

  test("директор читает экран и расходы, кнопок изменения нет, BFF на изменения отвечает 403", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await openIntegrations(page, "erp");
    await expect(page.getByText("Только просмотр")).toBeVisible();
    await expect(page.getByRole("button", { name: /^Проверить/ })).toHaveCount(0);
    await expect(
      side(page).getByText("Режим просмотра: изменения доступны администратору."),
    ).toBeVisible();
    await expect(side(page).getByRole("button", { name: "Ротация ключа" })).toHaveCount(0);
    await settledScreenshot(page, "director-readonly");

    // fetch из страницы: ответ даёт тот же мок BFF, что видит экран
    const status = await page.evaluate<number>(`(async () => {
      const csrf = /rt_pf_csrf=([^;]+)/.exec(document.cookie)?.[1] ?? "";
      const response = await fetch("/api/v1/admin/integrations/erp/rotate", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": decodeURIComponent(csrf) },
        body: JSON.stringify({ password: "x" }),
      });
      return response.status;
    })()`);
    expect(status).toBe(403);

    await openIntegrations(page, "spend");
    await expect(side(page).getByRole("table", { name: "Провайдеры за сегодня" })).toBeVisible();
    await settledScreenshot(page, "director-spend");

    // модели и копии директору — на чтение (W13-A1, решение архитектора по Q-W13-A1-1)
    await openIntegrations(page, "models");
    await expect(side(page).getByText("Диалог с клиентом")).toBeVisible();
    await expect(side(page).getByText("•••• 77aa").first()).toBeVisible();
    await expect(side(page).getByRole("button", { name: /^Сменить модель/ })).toHaveCount(0);
    await settledScreenshot(page, "director-models");
    await openIntegrations(page, "storage");
    await expect(side(page).getByText("crm-2026-10-26.dump")).toBeVisible();
    await expect(side(page).getByRole("button", { name: "Сделать копию сейчас" })).toHaveCount(0);
  });

  test("без раздела «Admin» пункта нет, прямой адрес — «Нет доступа»", async ({ page }) => {
    await loginAndWait(page, "manager@demo.example");
    await page.goto("/admin/integrations");
    await expect(page.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);
  });
});

test.describe("Внешние интеграции: axe и снимки", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`администратор на ${String(width)}: обзор и все карточки без нарушений axe`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "admin@demo.example");
      await openIntegrations(page);
      await expectNoViolations(page, `overview ${String(width)}`);
      await settledScreenshot(page, "a11y-overview");

      for (const card of CARDS) {
        await openIntegrations(page, card);
        await expect(side(page).getByRole("heading", { level: 3 }).first()).toBeVisible();
        // дожидаемся данных панели: скелетона и «Загрузка» уже нет
        await expect(side(page).locator(".ant-skeleton")).toHaveCount(0);
        await expectNoViolations(page, `${card} ${String(width)}`);
        await settledScreenshot(page, `a11y-${card}`);
      }

      // формы действий открыты: пароль, «Что произойдёт», ошибка
      await openIntegrations(page, "erp");
      await side(page).getByRole("button", { name: "Подключить заново" }).click();
      await expect(side(page).getByRole("form", { name: "Подключить ERP" })).toBeVisible();
      await expectNoViolations(page, `erp form ${String(width)}`);
      await openIntegrations(page, "telegram");
      await side(page).getByRole("button", { name: "Сменить токен" }).click();
      await expectNoViolations(page, `telegram form ${String(width)}`);
      await openIntegrations(page, "models");
      await side(page).getByRole("button", { name: "Сменить модель: Диалог с клиентом" }).click();
      await expectNoViolations(page, `models form ${String(width)}`);
      // W13C-F2: поле «Модель» без префикса провайдера; чужой префикс — ошибка у поля словами, без потери ключа и пароля
      const models = side(page).getByRole("form", { name: "Сменить модель: Диалог с клиентом" });
      await expect(models.getByLabel("Модель")).toHaveValue("claude-demo-chat");
      await tallScreenshot(page, "f2-model-default");
      await models.getByLabel("Модель").fill("openai/gpt-demo");
      await models.getByLabel("Ключ провайдера").fill("demo-provider-key-91zx");
      await password(models);
      await models.getByRole("button", { name: "Сменить модель" }).click();
      await expect(models.getByRole("alert")).toContainText("Имя модели не принято");
      await expect(models.getByLabel("Модель")).toHaveAttribute("aria-invalid", "true");
      await expect(models.getByLabel("Ключ провайдера")).toHaveValue("demo-provider-key-91zx");
      await expectNoViolations(page, `models form error ${String(width)}`);
      await tallScreenshot(page, "f2-model-error");
      await openIntegrations(page, "services");
      await side(page).getByRole("button", { name: "Выключить сервис: Telegram Bot API" }).click();
      await expectNoViolations(page, `services form ${String(width)}`);
    });

    test(`здоровье интеграций на ${String(width)}: группа, подробности, готовый текст, ключ, состояния (W15-H3)`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "admin@demo.example");
      await openIntegrations(page);
      const attention = page
        .getByRole("heading", { level: 2, name: "Требует внимания" })
        .locator("xpath=ancestor::section[1]");
      const row = attention.locator("li[data-group]").filter({ hasText: "Ключ OpenAI отклонён" });

      // одна причина — одна строка: состояние, что не работает, «с …», «Кто исправляет», одно главное действие
      await expect(row).toHaveCount(1);
      await expect(row.getByText("Сломано", { exact: true })).toBeVisible();
      await expect(row).toContainText(
        "не работают: поиск по базе знаний, проверка качества ответов",
      );
      await expect(row).toContainText("Кто исправляет:");
      await expect(row).toContainText("ключ и оплата — у владельца компании");
      await expect(row.getByRole("button", { name: /Ввести новый ключ/ })).toBeVisible();
      await expect(page.locator("body")).not.toContainText("invalid_api_key");
      await expectNoViolations(page, `h3 group ${String(width)}`);
      await tallScreenshot(page, "h3-attention-group");

      // сырой ответ — только под «Техническими подробностями» (свёрнуто)
      await row.getByRole("button", { name: "Технические подробности" }).click();
      await expect(row.getByText(/invalid_api_key/)).toBeVisible();
      await expect(row.getByRole("button", { name: "Скопировать для поддержки" })).toBeVisible();
      await row.getByRole("button", { name: /Написать владельцу/ }).click();
      await expect(
        row.getByRole("group", { name: "Готовый текст: владельцу компании" }),
      ).toBeVisible();
      await expectNoViolations(page, `h3 technical ${String(width)}`);
      await tallScreenshot(page, "h3-technical-open");

      // «Ввести новый ключ» — форма в самой строке, без ухода на другой экран
      await row.getByRole("button", { name: /Ввести новый ключ/ }).click();
      await expect(row.getByRole("form", { name: "Новый ключ OpenAI" })).toBeVisible();
      await expect(page).toHaveURL(/\/admin\/integrations$/);
      await expectNoViolations(page, `h3 key form ${String(width)}`);
      await tallScreenshot(page, "h3-key-form");

      // «Ожидаемо на стенде» — серым, «Не проверено — нажмите «Проверить»», «Выключено намеренно»
      await openIntegrations(page, "services");
      const panel = side(page);
      await expect(panel.getByText("Ожидаемо на стенде")).toBeVisible();
      await expect(panel.getByText("Не проверено — нажмите «Проверить»").first()).toBeVisible();
      await expect(panel.getByText("Выключено намеренно").first()).toBeVisible();
      await expect(attention.getByText(/Распознавание документов недоступно/)).toHaveCount(0);
      await expectNoViolations(page, `h3 states ${String(width)}`);
      // карточка «Внешние сервисы» целиком: высокое окно, снимок только боковой панели
      const wide = page.viewportSize()?.width ?? 1440;
      await page.setViewportSize({ width: wide, height: 3000 });
      const dir = process.env["E2E_SCREENSHOT_DIR"];
      if (dir) {
        await page.waitForTimeout(500);
        await panel.screenshot({ path: `${dir}/h3-states-${String(wide)}.png` });
      }
      await page.setViewportSize({ width: wide, height: wide === 390 ? 844 : 900 });
    });

    test(`директор на ${String(width)}: просмотр без нарушений axe`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await openIntegrations(page);
      await expectNoViolations(page, `director overview ${String(width)}`);
      await openIntegrations(page, "spend");
      await expect(side(page).locator(".ant-skeleton")).toHaveCount(0);
      await expectNoViolations(page, `director spend ${String(width)}`);
    });
  }
});
