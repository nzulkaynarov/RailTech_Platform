import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// КОНТР-1б на MSW: компанию завели клиентом по ошибке — сотрудник снимает роль одним действием на карточке, компания
// выходит из «Клиентов», в списке у неё нет типа «Клиент». Снимки 1512, 1440 и 390 с axe.
const dir = process.env["E2E_SCREENSHOT_DIR"];

for (const width of [1512, 1440, 390] as const) {
  test(
    `«Не клиент»: карточка и список после исправления, ${String(width)}`,
    { tag: "@mobile" },
    async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/crm/clients/4?panel=open&tab=card");
      const roles = page.getByRole("list", { name: "Роли" });
      await expect(roles.getByText("Клиент", { exact: true })).toBeVisible();
      await expect(page.getByRole("tab", { name: "Заявки и проекты" })).toBeVisible();
      await waitForMotionEnd(page);
      if (dir)
        await page.screenshot({
          path: `${dir}/not-client-before-${String(width)}.png`,
          fullPage: true,
        });
      await expectNoViolations(page, "карточка клиента до исправления");

      await page.getByRole("button", { name: "Не клиент" }).click();

      await expect(roles.getByText("Клиент", { exact: true })).toBeHidden();
      await expect(page.getByRole("tab", { name: "Заявки и проекты" })).toBeHidden();
      await expect(page.getByRole("button", { name: "Не клиент" })).toBeHidden();
      await waitForMotionEnd(page);
      if (dir)
        await page.screenshot({
          path: `${dir}/not-client-after-${String(width)}.png`,
          fullPage: true,
        });
      await expectNoViolations(page, "карточка после «Не клиент»");

      // список: компания осталась строкой (контакты и история на месте), но «Клиентом» больше не названа
      await spaGoto(page, "/crm/clients");
      await expect(page.getByRole("link", { name: /ООО Демо-Вагон/ }).first()).toBeVisible();
      await expect(page.getByText("Роль не указана", { exact: true }).first()).toBeVisible();
      await waitForMotionEnd(page);
      if (dir)
        await page.screenshot({
          path: `${dir}/not-client-list-${String(width)}.png`,
          fullPage: true,
        });
      await expectNoViolations(page, "список после «Не клиент»");
    },
  );
}
