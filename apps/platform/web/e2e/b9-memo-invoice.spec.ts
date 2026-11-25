import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";
import { openStep } from "./support/fields";

// Б-9: служебка с суммой не уходит без счёта партнёра — «Осталось» называет, что приложить; отметка «Счёт партнёра придёт
// позже» снимает требование. Снимки 1512, 1440 и 390 и axe — docs/screens/b9.
for (const width of [1512, 1440, 390] as const) {
  test(`служебка с суммой: счёт партнёра (${String(width)})`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/eds/new?type=memo");
    await expect(
      page.getByRole("heading", { level: 1, name: "Внутренний документ" }),
    ).toBeVisible();
    await openStep(page, "О чём");
    await page.getByLabel("Тема").fill("Оплата рельсов");
    await page.getByLabel("Сумма, сум").fill("1 500 000");
    await openStep(page, "Текст и вложения");
    await page.getByLabel("Текст", { exact: true }).fill("Прошу оплатить поставку.");
    await openStep(page, "Проверка и отправка");

    const send = page.getByRole("button", { name: "Отправить на согласование" });
    await expect(send).toBeDisabled();
    await expect(page.locator("#doc-remaining")).toContainText(
      "Приложите счёт партнёра или отметьте, что он придёт позже.",
    );
    await settledScreenshot(page, "invoice-required");
    await expectNoViolations(page, `служебка без счёта, ${String(width)}`);

    await openStep(page, "Текст и вложения");
    await page.getByRole("checkbox", { name: "Счёт партнёра придёт позже" }).check();
    await openStep(page, "Проверка и отправка");
    await expect(send).toBeEnabled();
    await settledScreenshot(page, "invoice-later");
  });
}
