import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";
import { pickAddressee } from "./support/fields";

// СУЩ-2.6, часть 2 на MSW (ADR-0028 п. 5, макет «Контрагент», лист 4): адресат письма — организация из контрагентов и
// человек из её карточки; текст без выбора адресатом не становится. Снимки 1440 и 390 с axe.
const dir = process.env["E2E_SCREENSHOT_DIR"];

for (const width of [1440, 390] as const) {
  test(
    `письмо: адресат ссылкой — организация и человек, ${String(width)}`,
    { tag: "@mobile" },
    async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/eds/new?type=letter");
      await expect(page.getByRole("heading", { level: 1, name: "Исходящее письмо" })).toBeVisible();
      await expect(page.getByLabel("Кому — человек")).toBeDisabled();

      await pickAddressee(page, "Демо-Путь", "АО «Демо-Путь»");
      await expect(page.getByText("ИНН 300000777", { exact: true })).toBeVisible();
      await page.getByLabel("Кому — человек").click();
      await page.locator(".ant-select-item-option").filter({ hasText: "Демо Клиентов" }).click();
      await expect(page.getByLabel("Кому (должность и ФИО)")).toHaveValue(
        "Главный инженер Демо Клиентов",
      );
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/addressee-person-${String(width)}.png` });
      await expectNoViolations(page, "адресат и человек");

      // правка названия снимает выбор: адресат — только из списка
      await page.getByLabel("Адресат (организация)").fill("ГНИ Мирабадского района");
      await expect(
        page.getByText(/Выберите из контрагентов или заведите организацию/),
      ).toBeVisible();
      await expect(page.getByLabel("Кому — человек")).toBeDisabled();
    },
  );
}
