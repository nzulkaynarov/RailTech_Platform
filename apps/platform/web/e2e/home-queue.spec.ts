import { expect, test } from "@playwright/test";

import { expectNoViolations } from "./support/axe";
import { loginAndWait, settledScreenshot } from "./support/app";

// «Главная · Что ждёт вас» (ГЛ-1) на MSW: группы срока, чипы вида работы со счётчиком, «почему у вас» в строке, кнопка с
// названием действия, «Вы ждёте других» с «Напомнить»; axe (WCAG 2.1 AA) и снимки 1440 и 390 (`E2E_SCREENSHOT_DIR`).
const WIDTHS = [1440, 390] as const;

test.describe("Главная: что ждёт вас", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("директор: группы, чипы со счётчиком, причина и действие в каждой строке", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    const queue = page.getByRole("region", { name: "Что ждёт вас" });
    await expect(
      queue.getByRole("heading", { level: 3, name: /^Просрочено · \d+$/ }),
    ).toBeVisible();
    await expect(queue.getByRole("heading", { level: 3, name: /^Сегодня · \d+$/ })).toBeVisible();

    const chips = queue.getByRole("group", { name: "Вид работы" });
    await expect(chips.getByRole("button", { name: /^Всё \d+$/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const sign = chips.getByRole("button", { name: /^Подписать \d+$/ });
    await expect(sign).toBeVisible();
    await sign.click();
    await expect(sign).toHaveAttribute("aria-pressed", "true");
    await expect(queue.getByText("Согласовать СЗ-2026/031")).toHaveCount(0);
    const signRow = queue.getByRole("listitem").filter({ hasText: "Подписать договор" }).first();
    await expect(signRow.getByText("Почему у вас:")).toBeVisible();
    await expect(signRow.getByRole("link", { name: /^Подписать: / })).toBeVisible();
    await chips.getByRole("button", { name: /^Всё \d+$/ }).click();

    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await expectNoViolations(page, `главная директора ${String(width)}`);
      await settledScreenshot(page, "home-queue-director");
      const overflow = await page.evaluate<number>(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth",
      );
      expect(overflow, `горизонтальная прокрутка на ${String(width)}`).toBeLessThanOrEqual(0);
    }
  });

  test("директор: «Вы ждёте других» — кто и сколько ждёт, «Напомнить» работает раз в час", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    const waiting = page.getByRole("region", { name: /^Вы ждёте других/ });
    await expect(waiting).toBeVisible();
    await expect(waiting.getByText(/на подписи у Рустам Каримов · 3 ч/)).toBeVisible();
    await expect(waiting.getByText(/на согласовании: Бухгалтер · 1 д/)).toBeVisible();

    const remind = waiting.getByRole("button", { name: "Напомнить: Ответ на требование" });
    await remind.click();
    await expect(remind).toBeDisabled(); // напомнили — следующий раз не раньше, чем через час
    await settledScreenshot(page, "home-queue-waiting");
    await expectNoViolations(page, "вы ждёте других");
  });

  test("@mobile менеджер: «Взять» — в строке, остальное открывает объект", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "manager@demo.example");
    const queue = page.getByRole("region", { name: "Что ждёт вас" });
    await expect(
      queue.getByRole("button", { name: "Взять: Взять в работу лида L-2041" }),
    ).toBeVisible();
    await expect(queue.getByRole("link", { name: "Ответить: Ответить лиду L-2050" })).toBeVisible();
    await settledScreenshot(page, "home-queue-manager");
    await expectNoViolations(page, "главная менеджера 390");
  });
});
