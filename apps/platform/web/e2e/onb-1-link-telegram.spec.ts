import { type Page, expect, test } from "@playwright/test";

import { login, settledScreenshot } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ОНБ-1.3 на MSW: «Подключить уведомления на телефон» одной строкой в приветствии первого входа и в пустой «Главной»; в приветствии нет
// «Ваша роль — …». Снимки 1512, 1440 и 390 и axe 0 (`E2E_SCREENSHOT_DIR=docs/screens/onb3-link-telegram`).
const WIDTHS = [1512, 1440, 390] as const;
const TELEGRAM = "Подключить уведомления на телефон";

async function sized(page: Page, name: string, ready: () => Promise<void>): Promise<void> {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await ready();
    await expectNoViolations(page, `${name} ${String(width)}`);
    const overflow = await page.evaluate<number>(
      "document.documentElement.scrollWidth - document.documentElement.clientWidth",
    );
    expect(overflow).toBeLessThanOrEqual(0);
    await settledScreenshot(page, name);
  }
}

test.describe("Подключить уведомления на телефон — одна строка", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("приветствие: последняя строка списка; роли нет; тап открывает бота", async ({
    page,
    context,
  }) => {
    await page.goto("/login");
    await page.evaluate('window.localStorage.setItem("rt-pf-mock-onboarding", "pending")');
    await login(page, "supply@demo.example"); // Telegram не привязан
    const welcome = page.getByRole("dialog", { name: /Добро пожаловать/ });
    await expect(welcome.getByText(/Ваша роль/)).toHaveCount(0);
    const link = welcome.getByRole("button", { name: TELEGRAM });
    await expect(link).toBeVisible();
    await sized(page, "welcome", async () => {
      await expect(link).toBeVisible();
    });

    // Сети нет: страницу бота подменяем заглушкой, важен адрес, на который открылась вкладка
    await context.route("https://t.me/**", (route) =>
      route.fulfill({ contentType: "text/html", body: "<title>bot</title>" }),
    );
    const opened = context.waitForEvent("page");
    await link.click();
    const bot = await opened;
    await bot.waitForURL(/t\.me\/rt_demo_bot\?start=staff_/);
  });

  test("привязанному Telegram строки нет", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate('window.localStorage.setItem("rt-pf-mock-onboarding", "pending")');
    await login(page, "manager@demo.example"); // Telegram привязан
    const welcome = page.getByRole("dialog", { name: /Добро пожаловать/ });
    await expect(welcome.getByRole("listitem").first()).toBeVisible();
    await page.waitForTimeout(500);
    await expect(welcome.getByRole("button", { name: TELEGRAM })).toHaveCount(0);
  });

  test("пустая «Главная»: одна кнопка в пустом состоянии", async ({ page }) => {
    await login(page, "admin@demo.example"); // очередь пуста
    await expect(page.getByRole("heading", { name: "Задач для вас нет" })).toBeVisible();
    // Telegram администратора в демо привязан: отвязываем тем же запросом, что и «Отвязать» в профиле
    await page.evaluate(`fetch("/api/v1/me/telegram-link", { method: "DELETE" })`);
    await page.reload();
    const empty = page.getByRole("main").getByRole("button", { name: TELEGRAM });
    await expect(empty).toBeVisible();
    await sized(page, "home-empty", async () => {
      await expect(empty).toBeVisible();
    });
  });
});
