import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// СЦ-10: строка расчёта, похожая на позицию каталога, показывает «Похоже: …» с «Выбрать» и «Новая позиция»; подтвердить её
// до решения нельзя (макет — доска 18 холста ключевых экранов, принят владельцем). Снимки — docs/screens/sc10-catalog-hint.
const NUMBER = "ЗВ-2026-097";
const DRIVE = "Привод стрелочный электромеханический СП-6М";
const WIDTHS = [1440, 390] as const;

for (const width of WIDTHS) {
  test(`похожая позиция: подсказка и выбор (${String(width)})`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, `/erp/calc/${encodeURIComponent(NUMBER)}`);
    await expect(
      page.getByRole("heading", { level: 1, name: `Расчёт по заявке ${NUMBER}` }),
    ).toBeVisible();

    await page.getByRole("button", { name: "Добавить строку" }).click();
    const form = page.getByRole("region", { name: "Новая строка расчёта" });
    await form.getByLabel("Наименование").fill("Привод СП-6М");
    await form.getByRole("button", { name: "Добавить" }).click();
    await expect(form).toHaveCount(0);

    const hint = page.getByText(`Похоже: ${DRIVE}`).first();
    await expect(hint).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Подтвердить строку «Привод СП-6М»" }).first(),
    ).toBeDisabled();
    await hint.scrollIntoViewIfNeeded();
    await expectNoViolations(page, "строка с подсказкой похожей позиции");
    await settledScreenshot(page, "calc-hint");

    await page
      .getByRole("button", { name: `Выбрать позицию каталога «${DRIVE}»` })
      .first()
      .click();
    await expect(page.getByText(`Похоже: ${DRIVE}`)).toHaveCount(0);
  });
}
