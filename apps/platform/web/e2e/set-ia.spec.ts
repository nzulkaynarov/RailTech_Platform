import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// SET-IA «Настройки: порядок и навигация» (владелец 2026-11-03; ресёрч docs/research/2026-11-02-flexibility/4-settings-ia.md
// §4.1): индекс «Все настройки» с поиском и пятью группами, страницы групп, редиректы старых адресов, группа «Настройки» в
// общем поиске, ⚙ в подменю модуля. axe 0 и снимки 1440 и 390 для PR (`E2E_SCREENSHOT_DIR=docs/screens/set-ia`).
const WIDTHS = [1440, 390] as const;

/** Снимок без следов наведения (указатель уводится в угол) и с начала основного окна. */
async function shot(page: Page, name: string): Promise<void> {
  await page.mouse.move(0, 0);
  await page.evaluate("document.getElementById('main-content')?.scrollTo(0, 0)");
  await settledScreenshot(page, name);
}

/** Свежая установка: администратор и ERP есть, остальные шаги первого запуска не сделаны. */
async function seedFreshSetup(page: Page): Promise<void> {
  const key = JSON.stringify("rt-pf-mock-setup");
  const state = {
    needsAdmin: false,
    code: "",
    fresh: true,
    companyCreated: true,
    done: { erp: true },
  };
  const value = JSON.stringify(JSON.stringify(state));
  await page.addInitScript(
    `if (!window.localStorage.getItem(${key})) window.localStorage.setItem(${key}, ${value});`,
  );
}

async function h1(page: Page, name: string): Promise<void> {
  await expect(page.getByRole("heading", { level: 1, name, exact: true })).toBeVisible();
}

/** Страница каждой группы: адрес, заголовок и имя снимка. */
const GROUP_PAGES = [
  ["people", "/admin/roles", "Роли и права"],
  ["company", "/admin/company", "Реквизиты и бланк"],
  ["channels", "/admin/telegram", "Telegram"],
  ["processes", "/admin/dictionaries", "Справочники"],
  ["system", "/admin/ai-spend", "Расходы на ИИ"],
] as const;

/** Старые адреса → новые: закладки, ссылки справки и «Что нового» открывают новое место. */
const LEGACY = [
  ["/admin/bot", "/admin/telegram", "Telegram"],
  ["/admin/bot?part=texts", "/admin/telegram?tab=texts", "Telegram"],
  ["/admin/bot?section=escalation", "/admin/timing", "Время и сроки"],
  ["/admin/bot?section=notifications", "/admin/notifications", "Уведомления"],
  ["/admin/bot?section=deals", "/admin/dictionaries?list=deals", "Справочники"],
  ["/admin/bot?section=web_form", "/admin/web-forms", "Формы сайта"],
  ["/admin/bot?section=budget", "/admin/ai-spend", "Расходы на ИИ"],
  ["/admin/bot?part=exports", "/admin/exports", "Выгрузки"],
  ["/admin/company?tab=details", "/admin/company", "Реквизиты и бланк"],
  ["/admin/company?tab=brand", "/admin/company?part=brand", "Реквизиты и бланк"],
  ["/admin/company?tab=numbering", "/admin/numbering", "Нумерация"],
  ["/admin/company?tab=platform", "/admin/taxes", "Налоги и валюты"],
  ["/admin/company?tab=templates", "/admin/templates", "Шаблоны документов"],
  ["/admin/company?tab=quote", "/admin/templates?tab=quote", "Шаблоны документов"],
  ["/admin/company?tab=reference", "/admin/dictionaries?list=countries", "Справочники"],
  ["/admin/company?tab=categories", "/admin/dictionaries?list=categories", "Справочники"],
  ["/admin/company?tab=charges", "/admin/dictionaries?list=charges", "Справочники"],
  ["/admin/docflow", "/admin/dictionaries?list=doc", "Справочники"],
  ["/admin/docflow?tab=templates", "/admin/resolutions", "Шаблоны резолюций"],
  ["/admin/docflow?tab=ai", "/admin/ai-spend", "Расходы на ИИ"],
  ["/admin/integrations?card=mail&panel=open", "/admin/mail", "Почта"],
  ["/admin/integrations?card=telegram&panel=open", "/admin/telegram", "Telegram"],
  ["/admin/tickets", "/dashboard/queue", "Задачи"],
] as const;

test.describe("Настройки: порядок и навигация (SET-IA)", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`администратор на ${String(width)}: индекс, поиск «почта» → Почта, страницы групп, axe 0`, async ({
      page,
    }) => {
      test.setTimeout(240_000);
      const mobile = width === 390;
      await page.setViewportSize({ width, height: mobile ? 844 : 900 });
      await loginAndWait(page, "admin@demo.example");

      await spaGoto(page, "/admin");
      await h1(page, "Все настройки");
      for (const group of ["Сотрудники", "Компания", "Подключения", "Журнал"]) {
        await expect(page.getByRole("region", { name: group })).toBeVisible();
      }
      await expectNoViolations(page, `index ${String(width)}`);
      await shot(page, "index");

      // Поиск на индексе: карточки фильтруются на месте, переход — на страницу
      const search = page.getByRole("searchbox", { name: "Найти настройку" });
      await search.fill("почта");
      const results = page.getByRole("region", { name: "Найденные настройки" });
      await expect(results.getByRole("link").first()).toContainText("Почта");
      await expectNoViolations(page, `search ${String(width)}`);
      await shot(page, "search");
      await results.getByRole("link").first().click();
      await expect(page).toHaveURL(/\/admin\/mail$/);
      await h1(page, "Почта");
      await expect(page.getByRole("heading", { name: "Приём: общий ящик (IMAP)" })).toBeVisible();
      await expectNoViolations(page, `mail ${String(width)}`);
      await shot(page, "page-mail");

      // Каждая группа: индекс только с ней (⚙ из модуля ведёт так же) и её страница
      for (const [group, path, title] of GROUP_PAGES) {
        await spaGoto(page, `/admin?group=${group}`);
        await h1(page, "Все настройки");
        await expect(page.getByRole("link", { name: "Все группы настроек" })).toBeVisible();
        await expect(page.locator(".pf-set-group")).toHaveCount(1);
        await expectNoViolations(page, `group ${group} ${String(width)}`);
        await shot(page, `group-${group}`);
        await spaGoto(page, path);
        await h1(page, title);
        await expectNoViolations(page, `${path} ${String(width)}`);
        await shot(page, `page-${group}`);
      }
    });
  }

  test("подменю: пять групп с заголовками; ⚙ «Документов» ведёт в «Процессы»; Ctrl K находит настройки", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/timing");
    await h1(page, "Время и сроки");
    const menu = page.getByRole("navigation", { name: "Разделы модуля" });
    for (const item of ["Сотрудники", "Подключения", "Журнал"]) {
      await expect(menu.getByRole("link", { name: item, exact: true })).toBeVisible();
    }
    await expect(menu.getByRole("link", { name: "Компания", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expectNoViolations(page, "menu");
    await shot(page, "menu-groups");

    // Последние пункты группы «Система» прокручиваются целиком над кнопкой «Пригласить сотрудника», длинная подпись — в
    // своей подсветке
    await spaGoto(page, "/admin/bus");
    await expect(menu.getByRole("link", { name: "Журнал", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await settledScreenshot(page, "menu-bus");

    await spaGoto(page, "/eds/documents");
    const gear = page.getByRole("link", { name: "Настройки: Компания" });
    await expect(gear).toBeVisible();
    await gear.click();
    await expect(page).toHaveURL(/\/admin\?group=company$/);
    await expect(page.getByRole("region", { name: "Компания" })).toBeInViewport();
    await expect(page.getByRole("region", { name: "Сотрудники" })).toHaveCount(0);

    await page.keyboard.press("Control+k");
    await page.keyboard.type("почта");
    const settings = page.getByRole("group", { name: "Настройки" });
    await expect(settings.getByRole("option").first()).toContainText("Почта");
    await expectNoViolations(page, "global search");
    await shot(page, "global-search");
    await settings.getByRole("option").first().click();
    await expect(page).toHaveURL(/\/admin\/mail$/);
  });

  for (const width of WIDTHS) {
    test(`свежая установка на ${String(width)}: чек-лист «Первый запуск» на индексе, axe 0`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await seedFreshSetup(page);
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin");
      await h1(page, "Все настройки");
      const checklist = page.getByRole("region", { name: /^Первый запуск: готово \d+ из \d+$/ });
      await expect(checklist).toBeVisible();
      await expect(checklist.getByRole("link", { name: "Продолжить настройку" })).toBeVisible();
      await expect(page.getByRole("region", { name: "Настройка Платформы" })).toHaveCount(0);
      await expectNoViolations(page, `first run ${String(width)}`);
      await shot(page, "index-first-run");
    });
  }

  test("каждый старый адрес Настроек открывает новое место", async ({ page }) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "admin@demo.example");
    for (const [from, to, title] of LEGACY) {
      await spaGoto(page, from);
      // Ждём сам адрес, а не заголовок: соседние адреса ведут на одну страницу («Справочники»), и её заголовок от прошлого
      // шага виден раньше, чем сработает переход
      const escaped = to.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      await expect(page, from).toHaveURL(new RegExp(`${escaped}$`));
      await h1(page, title);
    }
  });

  for (const width of WIDTHS) {
    test(`директор на ${String(width)}: Настройки на чтение — без «Обмена между системами» и чек-листа, axe 0`, async ({
      page,
    }) => {
      test.setTimeout(120_000);
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/admin");
      await h1(page, "Все настройки");
      const system = page.getByRole("region", { name: "Журнал" });
      await expect(system.getByRole("link", { name: /Журнал/ })).toBeVisible();
      await expect(system.getByRole("link", { name: /Обмен между системами/ })).toHaveCount(0);
      await expect(page.getByRole("region", { name: /^Первый запуск/ })).toHaveCount(0);
      await expectNoViolations(page, `director index ${String(width)}`);
      await shot(page, "director-index");

      await spaGoto(page, "/admin/timing");
      await h1(page, "Время и сроки");
      await expect(page.getByText("Только просмотр", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: /^Сохранить/ })).toHaveCount(0);
      await expectNoViolations(page, `director timing ${String(width)}`);
      await shot(page, "director-timing");

      await spaGoto(page, "/admin/telegram?tab=templates");
      await h1(page, "Telegram");
      await expect(
        page.getByRole("link", { name: "Открыть шаблон: Пришлю КП сегодня" }),
      ).toBeVisible();
      await expect(page.getByRole("link", { name: "Новый шаблон" })).toHaveCount(0);
      await expectNoViolations(page, `director telegram templates ${String(width)}`);
    });
  }
});
