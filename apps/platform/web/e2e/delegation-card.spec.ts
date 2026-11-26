import { expect, test } from "@playwright/test";

import { loginAndWait, screenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// СОТР-2: карточка сотрудника — «Что делегировано» и «Документы»; короткая форма приглашения.
for (const width of [1512, 1440, 390]) {
  test(`карточка «Что делегировано», ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/org?employee=u-demo-manager&panel=open");
    const panel = page.locator("#pf-context-panel");
    const approve = panel.getByRole("switch", { name: "Утверждать и отправлять КП" });
    await expect(approve).not.toBeChecked();
    await expect(panel.getByRole("button", { name: "Сохранить" })).toHaveCount(0);
    await expect(panel.getByRole("tab", { name: "Документы" })).toBeVisible();

    await approve.click();
    await expect(panel.getByRole("button", { name: "Сохранить" })).toBeVisible();
    await expect(panel.getByText("изменено", { exact: true })).toBeVisible();
    await screenshot(page, "delegation-card");
    await expectNoViolations(page, `delegation-card-${String(width)}`);

    await panel.getByRole("button", { name: "Сохранить" }).click();
    await expect(panel.getByRole("button", { name: "Сохранить" })).toHaveCount(0);
  });

  test(`добавить сотрудника: короткая форма, ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/org?invite=open&panel=open");
    const panel = page.locator("#pf-context-panel");
    await expect(panel.getByRole("combobox", { name: "Набор по должности" })).toBeVisible();
    await expect(panel.getByRole("checkbox")).toHaveCount(0);
    await screenshot(page, "delegation-invite");
    await expectNoViolations(page, `delegation-invite-${String(width)}`);
  });
}
