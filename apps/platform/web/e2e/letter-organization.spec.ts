import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";
import { expectCompany, openCompany } from "./support/fields";

// ЕД-6 на MSW: компании нет среди контрагентов — «Завести» последней строкой поля; новая компания сразу становится
// адресатом письма, дубль по ИНН предлагает существующую. Снимки 1440 и 390 с axe.
const dir = process.env["E2E_SCREENSHOT_DIR"];

for (const width of [1440, 390] as const) {
  test(
    `письмо: организация-адресат из письма, ${String(width)}`,
    { tag: "@mobile" },
    async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/eds/new?type=letter");
      await expect(page.getByRole("heading", { level: 1, name: "Исходящее письмо" })).toBeVisible();
      const field = page.getByLabel("Адресат (организация)", { exact: true });
      await openCompany(field);
      await field.fill("Таможенный комитет");
      const option = page
        .locator(".ant-select-item-option")
        .getByText("Завести «Таможенный комитет»");
      await expect(option).toBeVisible();
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/suggest-${String(width)}.png` });
      await option.click();

      const sheet = page.getByRole("dialog", { name: "Новая компания" });
      await expect(sheet.getByLabel("Название")).toHaveValue("Таможенный комитет");
      await sheet.getByLabel("ИНН").fill("200000123");
      await sheet.getByLabel("Адрес").fill("Ташкент, ул. Мустакиллик, 1");
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/new-company-${String(width)}.png` });
      await expectNoViolations(page, "новая компания");

      await sheet.getByRole("button", { name: "Завести" }).click();
      await expect(sheet).toBeHidden();
      await expectCompany(page, "Таможенный комитет");
      await expect(page.getByText("ИНН 200000123")).toBeVisible();

      // тот же ИНН у другого названия: вторая компания не заводится, в поле встаёт существующая
      await openCompany(field);
      await field.fill("Другое имя");
      await page.locator(".ant-select-item-option").getByText("Завести «Другое имя»").click();
      await sheet.getByLabel("ИНН").fill("300000777");
      await sheet.getByRole("button", { name: "Завести" }).click();
      await expect(sheet).toBeHidden();
      await expectCompany(page, "АО «Демо-Путь»");
    },
  );
}
