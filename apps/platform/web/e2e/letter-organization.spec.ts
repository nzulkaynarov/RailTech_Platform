import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// СУЩ-2.6 на MSW (ADR-0028 п. 5, макет «Контрагент», лист 4): адресата нет среди контрагентов — «Завести организацию»
// из подсказок поля адресата; новая организация сразу становится адресатом письма. Снимки 1440 и 390 с axe.
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
      const field = page.getByLabel("Адресат (организация)");
      await field.fill("Таможенный комитет");
      const option = page.getByText("+ Завести организацию «Таможенный комитет»");
      await expect(option).toBeVisible();
      if (dir) await page.screenshot({ path: `${dir}/suggest-${String(width)}.png` });
      await option.click();

      const sheet = page.getByRole("dialog", { name: "Новая организация" });
      await expect(sheet.getByLabel("Название")).toHaveValue("Таможенный комитет");
      await sheet.getByLabel("ИНН").fill("200000123");
      await sheet.getByLabel("Адрес").fill("Ташкент, ул. Мустакиллик, 1");
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/new-organization-${String(width)}.png` });
      await expectNoViolations(page, "новая организация");

      await sheet.getByRole("button", { name: "Завести" }).click();
      await expect(sheet).toBeHidden();
      await expect(field).toHaveValue("Таможенный комитет");
      await expect(page.getByText("ИНН 200000123")).toBeVisible();
    },
  );
}
