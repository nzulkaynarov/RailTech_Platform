import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, openAvatarMenu, settledScreenshot, waitForMotionEnd } from "./support/app";

// axe (WCAG 2.1 AA) на 1440, 1280 и 390 и скриншоты экранов рядом с артбордами «0. Каркас» и «v3 · 1. Dashboard»
// (`E2E_SCREENSHOT_DIR=<каталог>`, ORCHESTRATOR §7 п. 5).
const WIDTHS = [1440, 1280, 390] as const;

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

test.describe("axe и скриншоты", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`Моя очередь (директор) на ${String(width)}: axe без нарушений`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await expect(
        page.getByRole("heading", { level: 2, name: "Что сделать сейчас" }),
      ).toBeVisible();
      await expect(page.getByText("Наложить резолюцию на письмо ВХ-104/26")).toBeVisible();
      if (width >= 1200) {
        // Боковое окно в списке закрыто по умолчанию и открывается поверх очереди (ORCHESTRATOR §3 п. 18).
        await page.getByRole("button", { name: "Панель", exact: true }).click();
        await expect(
          page.getByRole("listitem").filter({ hasText: "Демо Бухгалтерова" }),
        ).toBeVisible();
      }
      await expectNoViolations(page, `dashboard ${String(width)}`);
      await settledScreenshot(page, "dashboard");

      if (width === 390) {
        await page.getByRole("button", { name: "Меню" }).click();
        await expect(page.getByRole("navigation", { name: "Разделы модуля" })).toBeVisible();
        await expectNoViolations(page, "menu drawer 390");
        await settledScreenshot(page, "dashboard-menu-drawer");
        await page.getByRole("link", { name: "Мои задачи 3, требует действия" }).click();
        await page.getByRole("button", { name: "Показать боковое окно" }).click();
        await expect(page.getByRole("tab", { name: "Сегодня" })).toBeVisible();
        await expectNoViolations(page, "panel drawer 390");
        await settledScreenshot(page, "dashboard-panel-drawer");
      }
    });

    test(`Нет доступа на ${String(width)}: axe без нарушений`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "manager@demo.example");
      await page.goto("/admin/roles");
      await expect(page.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
      await expectNoViolations(page, `forbidden ${String(width)}`);
      await settledScreenshot(page, "forbidden");
    });

    test(`Вход на ${String(width)}: axe без нарушений`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto("/login");
      await expect(page.getByRole("heading", { level: 1, name: "Вход в Платформу" })).toBeVisible();
      await expectNoViolations(page, `login ${String(width)}`);
      await settledScreenshot(page, "login");
    });

    test(`Раздел с боковым окном и свёрнутыми панелями на ${String(width)}: axe без нарушений`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "all@demo.example");
      await page.goto("/eds/inbox");
      await expect(page.getByRole("heading", { level: 1, name: "Входящие письма" })).toBeVisible();
      await expectNoViolations(page, `inbox ${String(width)}`);
      await settledScreenshot(page, "eds-inbox");
    });
  }

  test("меню аватара и страница профиля на 1440: axe без нарушений", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "all@demo.example");
    await openAvatarMenu(page);
    await expect(page.getByRole("menuitem", { name: "Выйти" })).toBeVisible();
    await settledScreenshot(page, "avatar-menu");
    await expectNoViolations(page, "avatar menu");
    await page.getByRole("menuitem", { name: "Профиль" }).click();
    // Профиль — страница /me (W15-H6), а не окно
    await expect(page).toHaveURL(/\/me$/);
    await expect(page.getByRole("heading", { level: 1, name: "Профиль" })).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expectNoViolations(page, "profile page");
  });

  test("центр уведомлений на 1440: axe без нарушений", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "director@demo.example");
    await page.getByRole("button", { name: /^Центр уведомлений/ }).click();
    await expect(page.getByText("КП-2026/118 ждёт вашего согласования")).toBeVisible();
    await expectNoViolations(page, "notifications popover");
  });
});
