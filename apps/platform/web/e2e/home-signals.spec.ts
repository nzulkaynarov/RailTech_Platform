import { expect, test } from "@playwright/test";

import { loginAndWait, openAvatarMenu, settledScreenshot } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ГЛ-2 «Сигналы» на MSW: число задач на значке «Главной» (рейл и нижняя панель) и в заголовке вкладки;
// переключатели Telegram «решения / прочие задачи» в профиле. Снимки 1440 и 390 — в docs/screens/home-signals/.
const WIDTHS = [1440, 390] as const;

for (const width of WIDTHS) {
  test(`Число задач на «Главной» и в заголовке вкладки на ${String(width)}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "director@demo.example");
    const home = page
      .getByRole("navigation", { name: "Модули" })
      .getByRole("link", { name: /^Главная: требуют действия — \d+$/ });
    await expect(home).toBeVisible();
    const count = (await home.locator("b").getAttribute("data-count")) ?? "";
    expect(Number(count)).toBeGreaterThan(0);
    // тот же номер, что бейдж «Задачи» в подменю и заголовок вкладки
    await expect(page).toHaveTitle(new RegExp(`^\\(${count}\\) `));
    await expect(page.getByRole("link", { name: /^Операции/ }).locator("b")).toHaveCount(0);
    await expectNoViolations(page, `значок задач ${String(width)}`);
    await settledScreenshot(page, "rail-count");
  });

  test(`Профиль: Telegram по решениям и по прочим задачам на ${String(width)}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "director@demo.example");
    await openAvatarMenu(page);
    await page.getByRole("menuitem", { name: "Профиль" }).click();
    await expect(page).toHaveURL(/\/me$/);
    const region = page.getByRole("region", { name: "Уведомления" });
    const decisions = region.getByRole("switch", { name: /Решения: подписать/ });
    const tasks = region.getByRole("switch", { name: /Прочие задачи/ });
    await expect(decisions).toBeVisible();
    await expect(tasks).toBeVisible();
    // по умолчанию: решения — да, прочие задачи — нет (Telegram в демо привязан не у всех: состояние переключателей то же)
    await expect(decisions).toHaveAttribute("aria-checked", "true");
    await expect(tasks).toHaveAttribute("aria-checked", "false");
    await expectNoViolations(page, `профиль: уведомления ${String(width)}`);
    // страница длиннее окна: кадр целиком, чтобы блок «Уведомления» попал на снимок
    await page.setViewportSize({ width, height: width === 390 ? 2800 : 1900 });
    await settledScreenshot(page, "profile-notifications");
  });
}
