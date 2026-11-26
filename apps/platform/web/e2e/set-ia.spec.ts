import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// SET-IA «Настройки: порядок и навигация» (владелец 2026-11-03) и ЕВ-2а (отчёт 2026-11-22 §8, доски 37 и 38): «Состояние»
// первым экраном и пять групп, меню страниц группы слева, две страницы настроек в общей рамке, редиректы старых адресов,
// группа «Настройки» в общем поиске, ⚙ в подменю модуля. axe 0 и снимки 1440 и 390 для PR
// (`E2E_SCREENSHOT_DIR=docs/screens/ev2a-settings`).
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
  ["rules", "/admin/sales", "Продажи"],
  ["channels", "/admin/telegram", "Telegram"],
  ["journal", "/admin/audit", "История"],
] as const;

/** Старые адреса → новые: закладки, ссылки справки и «Что нового» открывают новое место. */
const LEGACY = [
  ["/admin/bot", "/admin/telegram", "Telegram"],
  ["/admin/bot?part=texts", "/admin/telegram?tab=texts", "Telegram"],
  ["/admin/bot?section=escalation", "/admin/telegram?tab=behavior", "Telegram"],
  ["/admin/bot?section=notifications", "/admin/notifications", "Уведомления"],
  ["/admin/bot?section=deals", "/admin/dictionaries?list=deals", "Справочники"],
  ["/admin/bot?section=web_form", "/admin/web-forms", "Формы сайта"],
  ["/admin/bot?section=budget", "/admin/ai-spend", "ИИ"],
  ["/admin/bot?part=exports", "/admin/exports", "Выгрузки"],
  ["/admin/company?tab=details", "/admin/company", "Реквизиты и бланк"],
  ["/admin/company?tab=brand", "/admin/company?part=brand", "Реквизиты и бланк"],
  ["/admin/company?tab=numbering", "/admin/numbering", "Нумерация"],
  ["/admin/company?tab=platform", "/admin/taxes", "Налоги и валюты"],
  ["/admin/company?tab=templates", "/admin/templates?tab=documents", "Шаблоны"],
  ["/admin/company?tab=quote", "/admin/sales", "Продажи"],
  ["/admin/templates?tab=quote", "/admin/sales", "Продажи"],
  ["/admin/company?tab=reference", "/admin/dictionaries?list=countries", "Справочники"],
  ["/admin/company?tab=categories", "/admin/dictionaries?list=categories", "Справочники"],
  ["/admin/company?tab=charges", "/admin/dictionaries?list=charges", "Справочники"],
  ["/admin/docflow", "/admin/dictionaries?list=doc", "Справочники"],
  ["/admin/docflow?tab=templates", "/admin/templates?tab=resolutions", "Шаблоны"],
  ["/admin/resolutions", "/admin/templates?tab=resolutions", "Шаблоны"],
  ["/admin/docflow?tab=ai", "/admin/ai-spend", "ИИ"],
  ["/admin/integrations?card=mail&panel=open", "/admin/mail", "Почта"],
  ["/admin/integrations?card=telegram&panel=open", "/admin/telegram", "Telegram"],
  ["/admin/tickets", "/dashboard/queue", "Задачи"],
] as const;

test.describe("Настройки: порядок и навигация (SET-IA)", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`администратор на ${String(width)}: «Состояние», две страницы настроек в общей рамке, страницы групп, axe 0`, async ({
      page,
    }) => {
      test.setTimeout(240_000);
      const mobile = width === 390;
      await page.setViewportSize({ width, height: mobile ? 844 : 900 });
      await loginAndWait(page, "admin@demo.example");

      // «Состояние» — первый экран модуля: что требует внимания, службы, готовность
      await spaGoto(page, "/admin");
      await h1(page, "Состояние");
      await expect(page.getByRole("region", { name: /^Требует внимания · \d+$/ })).toBeVisible();
      await expect(page.getByRole("region", { name: "Службы" })).toBeVisible();
      await expect(page.getByRole("region", { name: /^Готовность · \d+ из \d+$/ })).toBeVisible();
      await expect(page.getByText("не подключена")).toBeVisible();
      await expectNoViolations(page, `state ${String(width)}`);
      await shot(page, "state");

      // Страница-форма в общей рамке: меню группы слева (на телефоне — список), «Подробнее», форма не шире 768
      await spaGoto(page, "/admin/timing");
      await h1(page, "Время и сроки");
      if (mobile) {
        await expect(page.getByRole("combobox", { name: /Страницы настроек/ })).toBeVisible();
      } else {
        const nav = page.getByRole("navigation", { name: "Разделы модуля" });
        await expect(nav.getByRole("link", { name: "Время и сроки" })).toHaveAttribute(
          "aria-current",
          "page",
        );
        const form = page.getByRole("region", { name: "Рабочие часы" });
        await expect(form).toBeVisible();
        expect((await form.boundingBox())?.width ?? 0).toBeLessThanOrEqual(768);
      }
      await expect(page.getByRole("link", { name: /^Подробнее/ })).toBeVisible();
      await expectNoViolations(page, `timing ${String(width)}`);
      await shot(page, "page-timing");

      // «Почта»: канал вместе с видами писем и правилами отправителей
      await spaGoto(page, "/admin/mail");
      await h1(page, "Почта");
      await expect(page.getByRole("heading", { name: "Приём: общий ящик (IMAP)" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Правила отправителей" })).toBeVisible();
      await expectNoViolations(page, `mail ${String(width)}`);
      await shot(page, "page-mail");

      // Каждая группа: первая страница по ⚙ (`?group=`) и страница группы
      for (const [group, path, title] of GROUP_PAGES) {
        await spaGoto(page, path);
        await h1(page, title);
        await expectNoViolations(page, `${path} ${String(width)}`);
        await shot(page, `page-${group}`);
      }
    });
  }

  test("подменю: «Состояние» и пять групп; ⚙ «Документов» ведёт в «Правила работы»; Ctrl K находит настройки", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/timing");
    await h1(page, "Время и сроки");
    const menu = page.getByRole("navigation", { name: "Разделы модуля" });
    await expect(menu.getByRole("link", { name: "Состояние", exact: true })).toBeVisible();
    for (const group of [
      "Люди и доступ",
      "Компания",
      "Правила работы",
      "Каналы и подключения",
      "Журнал",
    ]) {
      await expect(menu.getByRole("group", { name: group, exact: true })).toBeVisible();
    }
    // НАСТ-1: все страницы видны сразу; текущая — `page`
    await expect(menu.getByRole("link", { name: "Время и сроки", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expectNoViolations(page, "menu");
    await shot(page, "menu-groups");

    // «Обмен между системами» — вид «Истории»: подсвечена «История»
    await spaGoto(page, "/admin/bus");
    await expect(menu.getByRole("link", { name: "История", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await settledScreenshot(page, "menu-bus");

    await spaGoto(page, "/eds/documents");
    const gear = page.getByRole("link", { name: "Настройки: Правила работы" });
    await expect(gear).toBeVisible();
    await gear.click();
    // ⚙ ведёт на первую страницу группы, а не на «Состояние»
    await expect(page).toHaveURL(/\/admin\/sales$/);
    await h1(page, "Продажи");

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
    test(`свежая установка на ${String(width)}: «Готовность» на «Состоянии», axe 0`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await seedFreshSetup(page);
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin");
      await h1(page, "Состояние");
      const checklist = page.getByRole("region", { name: /^Готовность · \d+ из \d+$/ });
      await expect(checklist).toBeVisible();
      await expect(checklist.getByRole("link", { name: "Продолжить настройку" })).toBeVisible();
      await expect(page.getByRole("region", { name: "Настройка Платформы" })).toHaveCount(0);
      await expectNoViolations(page, `first run ${String(width)}`);
      await shot(page, "state-first-run");
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
    test(`директор на ${String(width)}: «Состояние» на чтение — без каналов и подключений, axe 0`, async ({
      page,
    }) => {
      test.setTimeout(120_000);
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/admin");
      await h1(page, "Состояние");
      await expect(page.getByRole("region", { name: /^Требует внимания · \d+$/ })).toBeVisible();
      await expect(page.getByRole("link", { name: "Продолжить настройку" })).toHaveCount(0);
      if (width === 1440) {
        const menu = page.getByRole("navigation", { name: "Разделы модуля" });
        await expect(menu.getByRole("group", { name: "Каналы и подключения" })).toHaveCount(0);
        await expect(menu.getByRole("group", { name: "Компания", exact: true })).toBeVisible();
      }
      // страницы раздела admin.system директору закрыты: кнопок на них на «Состоянии» нет
      for (const href of [
        "/admin/telegram",
        "/admin/mail",
        "/admin/integrations",
        "/admin/ai-spend",
      ]) {
        await expect(page.locator(`main a[href^="${href}"]`)).toHaveCount(0);
      }
      await expectNoViolations(page, `director state ${String(width)}`);
      await shot(page, "director-state");

      await spaGoto(page, "/admin/timing");
      await h1(page, "Время и сроки");
      await expect(page.getByText(/^Только просмотр/).first()).toBeVisible();
      await expect(page.getByRole("button", { name: /^Сохранить/ })).toHaveCount(0);
      await expectNoViolations(page, `director timing ${String(width)}`);
      await shot(page, "director-timing");

      // «Продажи» — коммерческое правило, директор его правит; страница фундамента («Telegram») ему не показывается
      await spaGoto(page, "/admin/sales");
      await h1(page, "Продажи");
      await expect(page.getByText(/^Только просмотр/)).toHaveCount(0);
      await spaGoto(page, "/admin/telegram");
      await h1(page, "Нет доступа");

      // ⚙ «Клиентов» ведёт в «Каналы и подключения»: у директора там нет страниц, значка нет
      await spaGoto(page, "/crm/leads");
      await expect(page.getByRole("link", { name: /^Настройки: Каналы/ })).toHaveCount(0);
    });
  }
});
