import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// СЦ-10: файлы, которые клиент приложил к заявке в кабинете, видны директору в карточке входящего и снабженцу в расчёте
// (до начала — под текстом заявки, после — в задании бокового окна). Снимки 1440 и 390 и axe — docs/screens/sc10-request-files.
const WIDTHS = [1440, 390] as const;

for (const width of WIDTHS) {
  test(`карточка письма: файл заявки вместо «Вложений нет» (${String(width)})`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, `/eds/inbox/${encodeURIComponent("ВХ-106/26")}`);
    await expect(page.getByRole("heading", { level: 1, name: "Письмо ВХ-106/26" })).toBeVisible();
    const files = page.getByRole("list", { name: "Из заявки ЗВ-2026-106" });
    await expect(files.getByRole("link", { name: "Скачать файл spec.pdf" })).toBeVisible();
    await expect(page.getByText("Вложений нет")).toHaveCount(0);
    await expectNoViolations(page, "карточка письма с файлом заявки");
    await settledScreenshot(page, "letter-request-files");
  });

  test(`расчёт до начала: файл под текстом заявки (${String(width)})`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, `/erp/calc/${encodeURIComponent("ЗВ-2026-103")}`);
    await expect(page.getByRole("heading", { name: "Расчёт ещё не начат" })).toBeVisible();
    await expect(
      page
        .getByRole("list", { name: "Файлы заявки" })
        .getByRole("link", { name: "Скачать файл Ведомость брусьев.xlsx" }),
    ).toBeVisible();
    await expectNoViolations(page, "расчёт до начала с файлом заявки");
    await settledScreenshot(page, "calc-request-files");
  });
}

test("задание в боковом окне: ссылка на файл заявки", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await loginAndWait(page, "supply@demo.example");
  await spaGoto(page, "/erp/requests");
  await page
    .getByRole("link", { name: "Показать задание по заявке ЗВ-2026-097 в боковом окне" })
    .click();
  const link = page.getByRole("link", { name: "Скачать файл spec.pdf" });
  await expect(link).toBeVisible();
  // Скачивание идёт мимо MSW (навигация браузера) — здесь адрес; поток и заголовки проверяет BFF.
  await expect(link).toHaveAttribute(
    "href",
    `/api/v1/erp/calc/${encodeURIComponent("ЗВ-2026-097")}/request-files/7`,
  );
  await expectNoViolations(page, "задание с файлом заявки");
  await settledScreenshot(page, "task-request-files");
});
