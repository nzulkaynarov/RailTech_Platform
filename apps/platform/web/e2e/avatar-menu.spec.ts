import { expect, test } from "@playwright/test";

import { loginAndWait, openAvatarMenu, screenshot } from "./support/app";
import { expectNoViolations } from "./support/axe";

// СОТР-2: в меню аватара нет «Активной роли»; у сотрудника с несколькими ролями всё делегированное — сразу.
for (const width of [1512, 390]) {
  test(`меню аватара без переключателя ролей, ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await loginAndWait(page, "all@demo.example");
    await openAvatarMenu(page);
    for (const name of ["Профиль", "Помощь", "Сменить пароль", "Выйти"]) {
      await expect(page.getByRole("menuitem", { name })).toBeVisible();
    }
    await expect(page.getByText("Активная роль")).toHaveCount(0);
    await expect(page.getByRole("menuitem", { name: "Все роли" })).toHaveCount(0);
    await screenshot(page, "avatar-menu");
    await expectNoViolations(page, `avatar-menu-${String(width)}`);
  });
}
