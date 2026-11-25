import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";
import { chooseOrAddAddressee, pickFiles } from "./support/fields";

// Б-7: после «Создать заявку» — номер, «Ждёт резолюции.» и «Открыть заявку». Снимки 1512 и 1440 и axe (390 — в crm-leads-clients.spec.ts, @mobile) — docs/screens/b7.
const LETTER = {
  name: "pismo-direktoru.pdf",
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.4\n% демо-письмо\n"),
};

for (const width of [1512, 1440] as const) {
  test(`заявка создана: номер и что дальше (${String(width)})`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/crm/leads");
    const table = page.getByRole("table", { name: "Лиды" });
    await table.getByRole("link", { name: "Открыть карточку Азиз Демо" }).click();
    await page.getByRole("button", { name: "Скрыть боковое окно" }).click();
    await page.getByRole("link", { name: "Создать заявку для Азиз Демо" }).click();
    const form = page.getByRole("form", { name: "Создать заявку" });
    await chooseOrAddAddressee(page, "ООО Демо-Логистик", "Название компании");
    await form.getByRole("button", { name: /^Запрос/, expanded: false }).click();
    await pickFiles(form.getByLabel("Письмо или файл запроса"), LETTER);
    await expect(form.getByText(`Загружено: ${LETTER.name}`)).toBeVisible();
    await form.getByRole("button", { name: /^Проверка и отправка/, expanded: false }).click();
    await form.getByRole("button", { name: /Создать заявку/ }).click();

    const done = page.getByRole("status").filter({ hasText: "Заявка создана" });
    await expect(done.getByText("RQ-2026-040")).toBeVisible();
    await expect(done.getByText("Ждёт резолюции.")).toBeVisible();
    await expect(done.getByRole("link", { name: "Открыть заявку" })).toBeVisible();
    await settledScreenshot(page, "request-done");
    await expectNoViolations(page, `заявка создана, ${String(width)}`);
  });
}
