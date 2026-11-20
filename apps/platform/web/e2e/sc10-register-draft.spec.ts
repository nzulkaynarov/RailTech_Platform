import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// СЦ-10: незаконченная регистрация входящего сохраняется с файлом; при возврате — «Продолжить» или «Начать заново».
// Снимки 1440 и 390 и axe — docs/screens/sc10-register-draft.
const WIDTHS = [1440, 390] as const;

for (const width of WIDTHS) {
  test(`черновик регистрации с файлом (${String(width)})`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "registrar@demo.example");
    await spaGoto(page, "/eds/register");
    await expect(
      page.getByRole("heading", { level: 1, name: "Регистрация входящего документа" }),
    ).toBeVisible();
    await page.getByLabel("Файл документа").setInputFiles({
      name: "trebovanie.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4"),
    });
    await expect(
      page.getByRole("list", { name: "Прикреплённые файлы" }).getByText("загружен"),
    ).toBeVisible();

    await spaGoto(page, "/eds/inbox");
    await expect(page.getByRole("heading", { level: 1, name: "Входящие" })).toBeVisible();
    await spaGoto(page, "/eds/register");
    const banner = page.getByText(/^Черновик от .*: trebovanie\.pdf$/);
    await expect(banner).toBeVisible();
    await expectNoViolations(page, "плашка черновика регистрации");
    await settledScreenshot(page, "register-draft-offer");

    await page.getByRole("button", { name: "Продолжить" }).click();
    await expect(
      page.getByRole("list", { name: "Прикреплённые файлы" }).getByText("trebovanie.pdf"),
    ).toBeVisible();
    await expectNoViolations(page, "форма после «Продолжить»");
    await settledScreenshot(page, "register-draft-continued");
  });
}
