import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// W15-H4 «Настройки без переброса» на MSW (UX-оценка 2026-10-27 §5 P1-6): шаги первого запуска — в боковом окне мастера,
// пункт «Первый запуск» до завершения, «Скрыть до завтра»; Telegram-бот в одном месте с вкладками; один «Журнал» с фильтром
// «Действия людей / Обмен между системами»; боковое окно закрыто, где выбирать нечего. axe 0 и снимки 1440 и 390 для PR
// (`E2E_SCREENSHOT_DIR=docs/screens/w15-h4`).
const WIDTHS = [1440, 390] as const;
const PANEL = "#pf-context-panel";
const SETUP_KEY = "rt-pf-mock-setup";

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

/** Снимок с начала основного окна: проверки выше могли прокрутить его к найденному тексту. */
async function shot(page: Page, name: string): Promise<void> {
  await page.evaluate("document.getElementById('main-content')?.scrollTo(0, 0)");
  await settledScreenshot(page, name);
}

/** Свежая установка с администратором и сопряжённой ERP: остальные шаги не сделаны, компании нет. */
async function seedFreshSetup(page: Page): Promise<void> {
  const state = {
    needsAdmin: false,
    code: "",
    fresh: true,
    companyCreated: true,
    done: { erp: true },
  };
  const key = JSON.stringify(SETUP_KEY);
  const value = JSON.stringify(JSON.stringify(state));
  await page.addInitScript(
    `if (!window.localStorage.getItem(${key})) window.localStorage.setItem(${key}, ${value});`,
  );
}

test.describe("Настройки без переброса", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`мастер, бот, журнал и подключения на ${String(width)}: без перехода между экранами, axe 0`, async ({
      page,
    }) => {
      test.setTimeout(180_000);
      const mobile = width === 390;
      await page.setViewportSize({ width, height: mobile ? 844 : 900 });
      await seedFreshSetup(page);
      await loginAndWait(page, "admin@demo.example");

      // Баннер: «Скрыть до завтра»
      await spaGoto(page, "/admin/org");
      const banner = page.getByRole("region", { name: "Настройка Платформы" });
      await expect(
        banner.getByRole("button", { name: "Скрыть до завтра: баннер настройки" }),
      ).toHaveText("Скрыть до завтра");
      await expectNoViolations(page, `banner ${String(width)}`);
      await shot(page, "banner");

      // Мастер: пункт меню есть, пока шаги не завершены; шаг открывается в боковом окне мастера
      if (!mobile) {
        await expect(
          page
            .getByRole("navigation", { name: "Разделы модуля" })
            .getByRole("link", { name: "Первый запуск" }),
        ).toBeVisible();
      }
      await banner.getByRole("link", { name: "Продолжить настройку" }).click();
      await expect(page.getByRole("heading", { level: 1, name: "Первый запуск" })).toBeVisible();
      await expect(page.getByRole("complementary", { name: "Боковое окно" })).toHaveCount(0);
      await shot(page, "wizard");
      await page
        .getByRole("list", { name: "Шаги настройки" })
        .getByRole("link", { name: "Подключить бота" })
        .click();
      await expect(page).toHaveURL(/\/admin\/setup\?step=bot/);
      const step = page.locator(PANEL).getByRole("region", { name: "Шаг 2 из 5: Telegram-бот" });
      await expect(step).toBeVisible();
      await expect(step.getByText("@demo_railtech_bot")).toBeVisible();
      await expect(page.getByRole("heading", { level: 1, name: "Первый запуск" })).toBeVisible();
      await expectNoViolations(page, `wizard step ${String(width)}`);
      await shot(page, "wizard-step-bot");

      // Telegram-бот в одном месте
      await spaGoto(page, "/admin/bot");
      await expect(page.getByRole("heading", { level: 1, name: "Telegram-бот" })).toBeVisible();
      await expect(page.getByRole("complementary", { name: "Боковое окно" })).toHaveCount(0);
      await expect(page.getByRole("tabpanel").getByText("@demo_railtech_bot")).toBeVisible();
      await expect(page.locator(".ant-skeleton")).toHaveCount(0);
      await expectNoViolations(page, `bot connection ${String(width)}`);
      await shot(page, "bot-connection");
      await page.getByRole("tab", { name: "База знаний" }).click();
      await expect(page.getByRole("link", { name: "Открыть базу знаний" })).toBeVisible();
      await expect(page.locator(".ant-skeleton")).toHaveCount(0);
      await expectNoViolations(page, `bot kb ${String(width)}`);
      await shot(page, "bot-kb");

      // Один журнал с фильтром
      await spaGoto(page, "/admin/audit");
      await expect(page.getByRole("heading", { level: 1, name: "Журнал" })).toBeVisible();
      const filter = page.getByRole("navigation", { name: "Что показать в журнале" });
      await expect(filter.getByRole("link", { name: "Действия людей" })).toHaveAttribute(
        "aria-current",
        "page",
      );
      await expect(page.getByRole("complementary", { name: "Боковое окно" })).toHaveCount(0);
      await expect(page.getByText("Записей: 13")).toBeVisible();
      await expectNoViolations(page, `journal people ${String(width)}`);
      await shot(page, "journal-people");
      await filter.getByRole("link", { name: "Обмен между системами" }).click();
      await expect(page).toHaveURL(/\/admin\/bus$/);
      await expect(page.getByRole("heading", { level: 3, name: "CRM отправляет" })).toBeVisible();
      await expect(page.getByRole("complementary", { name: "Боковое окно" })).toHaveCount(0);
      await expectNoViolations(page, `journal systems ${String(width)}`);
      await shot(page, "journal-systems");

      // Подключения: без «Объект не выбран»; у бота — кратко и «Настроить бота»
      await spaGoto(page, "/admin/integrations");
      await expect(page.getByRole("heading", { level: 2, name: "Сервисы" })).toBeVisible();
      await expect(page.getByRole("complementary", { name: "Боковое окно" })).toHaveCount(0);
      await expect(page.getByRole("link", { name: "Настройка Платформы" })).toBeVisible();
      await expectNoViolations(page, `integrations ${String(width)}`);
      await shot(page, "integrations");
      await spaGoto(page, "/admin/integrations?card=telegram&panel=open");
      await expect(page.locator(PANEL).getByRole("link", { name: "Настроить бота" })).toBeVisible();
      await expectNoViolations(page, `integrations telegram ${String(width)}`);
      await shot(page, "integrations-telegram");
    });
  }
});
