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
  ["/admin/tickets", "/dashboard/queue", "Мои задачи"],
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
      for (const group of ["Люди и доступ", "Компания", "Каналы связи", "Процессы", "Система"]) {
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
    for (const group of ["Люди и доступ", "Компания", "Каналы связи", "Процессы", "Система"]) {
      await expect(menu.getByRole("group", { name: group })).toBeVisible();
    }
    await expect(
      menu.getByRole("group", { name: "Процессы" }).getByRole("link", { name: "Время и сроки" }),
    ).toHaveAttribute("aria-current", "page");
    await expectNoViolations(page, "menu");
    await shot(page, "menu-groups");

    // Последние пункты группы «Система» прокручиваются целиком над кнопкой «Пригласить сотрудника», длинная подпись — в
    // своей подсветке
    await spaGoto(page, "/admin/bus");
    const bus = menu.getByRole("link", { name: "Обмен между системами" });
    await expect(bus).toHaveAttribute("aria-current", "page");
    await bus.scrollIntoViewIfNeeded();
    const invite = page.getByRole("link", { name: "Пригласить сотрудника" });
    for (const name of ["Выгрузки", "Обмен между системами"]) {
      const item = await menu.getByRole("link", { name, exact: true }).boundingBox();
      const button = await invite.boundingBox();
      expect((item?.y ?? 0) + (item?.height ?? 0), name).toBeLessThanOrEqual(button?.y ?? 0);
    }
    const label = await bus.locator("span").first().boundingBox();
    const box = await bus.boundingBox();
    expect((label?.y ?? 0) + (label?.height ?? 0)).toBeLessThanOrEqual(
      (box?.y ?? 0) + (box?.height ?? 0),
    );
    await page.mouse.move(0, 0);
    await settledScreenshot(page, "menu-bus");

    await spaGoto(page, "/eds/documents");
    const gear = page.getByRole("link", { name: "Настройки: Процессы" });
    await expect(gear).toBeVisible();
    await gear.click();
    await expect(page).toHaveURL(/\/admin\?group=processes$/);
    await expect(page.getByRole("region", { name: "Процессы" })).toBeInViewport();
    await expect(page.getByRole("region", { name: "Люди и доступ" })).toHaveCount(0);

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
      await h1(page, title);
      const url = new URL(page.url());
      expect(`${url.pathname}${url.search}`, from).toBe(to);
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
      const system = page.getByRole("region", { name: "Система" });
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
    });
  }
});
