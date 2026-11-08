import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";
import { chooseOption } from "./support/fields";

// FX-2: документ, присланный партнёром из кабинета, ждёт решения сотрудника в «Техдокументации» и до одобрения клиенту не виден.
// Снабженец фильтрует «Ждут проверки», открывает файл, одобряет; снимки 1440 и 390 px и axe (WCAG 2.1 AA) на MSW.

const WIDTHS = [1440, 390] as const;

for (const width of WIDTHS) {
  test(`документы партнёров на проверке, ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/erp/docs");
    await expect(page.getByRole("heading", { level: 1, name: "Техдокументация" })).toBeVisible();
    await expect(page.getByText("Протокол испытаний рельса (партнёр)").first()).toBeVisible();
    await expect(page.getByText("На проверке").first()).toBeVisible();
    await expectNoViolations(page, "Техдокументация · файл партнёра на проверке");
    await settledScreenshot(page, "docs-partner-list");

    // Очередь: фильтр оставляет только ждущие решения
    await chooseOption(page.getByRole("combobox", { name: "Проверка" }), "Ждут проверки");
    await expect(page.getByText("Сертификат соответствия на кабель")).toHaveCount(0);
    await expect(page.getByText("Протокол испытаний рельса (партнёр)").first()).toBeVisible();

    // Карточка файла: кто прислал, пояснение и решение
    await spaGoto(page, "/erp/docs?doc=5");
    const drawer = page.getByRole("dialog", { name: "Протокол испытаний рельса (партнёр)" });
    await expect(drawer.getByText("Завод Север")).toBeVisible();
    await expect(drawer.getByText(/Пока вы не одобрите его, клиенты его не видят/)).toBeVisible();
    await expect(drawer.getByRole("button", { name: "Одобрить" })).toBeVisible();
    await expect(drawer.getByRole("button", { name: "Отклонить" })).toBeVisible();
    await expectNoViolations(page, "Техдокументация · решение по файлу партнёра");
    await settledScreenshot(page, "docs-partner-review");

    await drawer.getByRole("button", { name: "Одобрить" }).click();
    // решённый файл уходит из очереди «Ждут проверки»
    await expect(page.getByText("Файла нет в списке")).toBeVisible();
  });
}
