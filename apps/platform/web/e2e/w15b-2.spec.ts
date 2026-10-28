import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import {
  login,
  loginAndWait,
  openAvatarMenu,
  settledScreenshot,
  waitForMotionEnd,
} from "./support/app";

// W15b-2 на MSW: мелкие дефекты гейта волны 15 — axe на приветствии первого входа менеджера (W15-G-4) и на «Ответ
// отправлен» (W15-G-5), узбекская дата (W15-G-9), «Каналы связи» -> «Telegram-бот» (W15-G-8). Снимки 1440 и 390.
const WIDTHS = [1440, 390] as const;

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

async function shoot(page: Page, name: string): Promise<void> {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await expectNoViolations(page, `${name} ${String(width)}`);
    await settledScreenshot(page, name);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

async function signOut(page: Page): Promise<void> {
  await openAvatarMenu(page);
  await page.getByRole("menuitem", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login/);
}

test.describe("Мелкие дефекты гейта волны 15", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("W15-G-4: приветствие первого входа менеджера — axe 0", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate('window.localStorage.setItem("rt-pf-mock-onboarding", "pending")');
    await login(page, "manager@demo.example");
    await expect(page).toHaveURL(/\/dashboard\/queue$/);
    await expect(page.getByRole("dialog", { name: /Добро пожаловать/ })).toBeVisible();
    await shoot(page, "g4-welcome-manager");
  });

  test("W15-G-5: «Ответ отправлен» в карточке обращения — контраст не ниже 4,5:1", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await page.goto("/admin/org");
    await page.getByRole("button", { name: "Написать администратору" }).click();
    const dialog = page.getByRole("dialog", { name: "Написать администратору" });
    await dialog
      .getByRole("textbox", { name: "Что случилось" })
      .fill("Нужен доступ к Оргструктуре");
    await dialog.getByRole("button", { name: "Отправить" }).click();
    await page
      .getByRole("dialog", { name: /отправлено/ })
      .getByRole("button", { name: "Закрыть", exact: true })
      .click();
    await signOut(page);

    await login(page, "admin@demo.example");
    await expect(page).toHaveURL(/\/dashboard\/queue$/);
    await page.goto("/admin/tickets/ОБР-0001?panel=open&tab=card");
    await page.getByRole("textbox", { name: "Ваш ответ" }).fill("Доступ выдан");
    await page.getByRole("button", { name: "Отправить ответ" }).click();
    await expect(page.getByText("Ответ отправлен")).toBeVisible();
    await shoot(page, "g5-ticket-answer-sent");
  });

  test("W15-G-9: на узбекском дата в «Моих задачах» — «28-oktabr 2026, chorshanba»", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await openAvatarMenu(page);
    await page.getByRole("menuitem", { name: "O‘zbekcha" }).click();
    await expect(page.getByRole("main")).toContainText(
      /\d{1,2}-(yanvar|fevral|mart|aprel|may|iyun|iyul|avgust|sentabr|oktabr|noyabr|dekabr) \d{4}, (yakshanba|dushanba|seshanba|chorshanba|payshanba|juma|shanba)/,
    );
    await expect(page.getByRole("main")).not.toContainText(/M\d{2}|Wed|Tue|Mon|Thu|Fri|Sat|Sun/);
    await shoot(page, "g9-uz-queue-date");
  });

  test("W15-G-8: заглушка «Каналы связи» ведёт в «Настройки · Telegram-бот»", async ({ page }) => {
    await loginAndWait(page, "all@demo.example");
    await page.goto("/crm/channels");
    const open = page.getByRole("link", { name: "Открыть «Telegram-бот»" });
    await expect(open).toHaveAttribute("href", "/admin/bot");
    await expect(page.getByRole("main")).not.toContainText("Подключения");
    await shoot(page, "g8-channels-stub");
  });
});
