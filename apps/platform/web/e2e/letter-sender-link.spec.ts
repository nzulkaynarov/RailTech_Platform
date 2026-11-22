import { expect, test } from "@playwright/test";

import { loginAndWait, reveal, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";
import { clearCompany, expectCompany, pickAddressee, openCompany } from "./support/fields";

// ЕД-6 на MSW: корреспондент входящего — компания из контрагентов и человек из её карточки; свободного текста нет;
// выбранный человек подставляет «Подписал». Снимки 1440 и 390 с axe.
const dir = process.env["E2E_SCREENSHOT_DIR"];
const SENDER = "Корреспондент (организация)";

for (const width of [1440, 390] as const) {
  test(
    `входящее: корреспондент ссылкой — организация и человек, ${String(width)}`,
    { tag: "@mobile" },
    async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "registrar@demo.example");
      await spaGoto(page, "/eds/register");
      await expect(
        page.getByRole("heading", { level: 1, name: "Регистрация входящего документа" }),
      ).toBeVisible();
      await reveal(page.getByLabel(SENDER, { exact: true }));
      await expect(page.getByLabel("Человек корреспондента")).toBeDisabled();

      await pickAddressee(page, "Демо-Путь", "АО «Демо-Путь»", SENDER);
      await expect(page.getByText("ИНН 300000777", { exact: true })).toBeVisible();
      await page.getByLabel("Человек корреспондента").click();
      await page.locator(".ant-select-item-option").filter({ hasText: "Демо Клиентов" }).click();
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/sender-person-${String(width)}.png` });
      await expectNoViolations(page, "корреспондент и человек");

      await expect(page.getByLabel("Подписал")).toHaveValue("Демо Клиентов");

      // текст в поле — только запрос: без выбора корреспондент не меняется; очистка выключает «человека»
      const field = page.getByLabel(SENDER, { exact: true });
      await openCompany(field);
      await field.fill("ГНИ Мирабадского района");
      await page.keyboard.press("Escape");
      await expectCompany(page, "АО «Демо-Путь»", SENDER);
      await clearCompany(field);
      await expect(page.getByLabel("Человек корреспондента")).toBeDisabled();
    },
  );
}
