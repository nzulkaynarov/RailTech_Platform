import { expect, test } from "@playwright/test";

import { login, settledScreenshot } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ЕВ-5а: подсказка первого входа и пустая «Главная» — по разделам прав, а не по названию роли. Делопроизводитель и юрист
// получают свои тексты, а не «любая роль». Снимки 1440 и 390 с axe.
const WIDTHS = [1440, 390] as const;
const size = (width: number) => ({ width, height: width === 390 ? 844 : 900 });

test.describe("ЕВ-5а: роли — тексты по разделам", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    for (const who of [
      {
        key: "registrar",
        email: "registrar@demo.example",
        name: "Демо Канцелярова",
        first: "«Документы · Входящие»: зарегистрируйте пришедшее письмо",
      },
      {
        key: "lawyer",
        email: "lawyer@demo.example",
        name: "Демо Юристов",
        first: "«Задачи»: договоры ждут вашей визы",
      },
    ] as const) {
      test(`первый вход: ${who.key} видит свой текст, ${String(width)}`, async ({ page }) => {
        await page.setViewportSize(size(width));
        await page.goto("/login");
        await page.evaluate('window.localStorage.setItem("rt-pf-mock-onboarding", "pending")');
        await login(page, who.email);
        await expect(page).toHaveURL(/\/dashboard\/queue$/);
        const welcome = page.getByRole("dialog", { name: `Добро пожаловать, ${who.name}` });
        await expect(welcome).toBeVisible();
        await expect(welcome.getByText(who.first)).toBeVisible();
        // не текст «любой роли»
        await expect(welcome.getByText("Откройте «Задачи»")).toHaveCount(0);
        await expectNoViolations(page, `welcome ${who.key} ${String(width)}`);
        await settledScreenshot(page, `welcome-${who.key}`);
      });
    }

    test(`пустая «Главная» юриста: свой текст, ${String(width)}`, async ({ page }) => {
      await page.setViewportSize(size(width));
      await login(page, "lawyer@demo.example");
      await expect(page).toHaveURL(/\/dashboard\/queue$/);
      await expect(
        page.getByText("Договоры на вашу визу появятся здесь и в колокольчике."),
      ).toBeVisible();
      await expectNoViolations(page, `lawyer home ${String(width)}`);
      await settledScreenshot(page, `home-lawyer`);
    });
  }
});
