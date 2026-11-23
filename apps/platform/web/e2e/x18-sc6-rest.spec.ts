import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// Х-18: основание заявки без файла у лида любого канала («Записка о запросе»); галочки шагов по одной проверке с названной
// причиной на шаге — в заказе партнёру, форме партнёра и реквизитах. Снимки 1440 и 390 и axe — в docs/screens/x18-sc6-rest.

const WIDTHS = [1440, 390] as const;

async function shot(page: Page, name: string, width: number): Promise<void> {
  await waitForMotionEnd(page);
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (dir) await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
}

test.describe("Х-18: остаток СЦ-6", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаются спеком");

  for (const width of WIDTHS) {
    test(`лид не со звонка: записка о запросе собирается сама, файл не нужен, ${String(width)} px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/crm/leads?lead=L-2044&create=1&panel=open&tab=card");
      const form = page.getByRole("form", { name: "Создать заявку" });
      await expect(form).toBeVisible();
      await form.getByRole("button", { name: /^Запрос/ }).click();
      await expect(form.getByText("Записка о запросе приложена")).toBeVisible();
      await expect(form.getByRole("button", { name: /^Открыть/ })).toBeVisible();
      await shot(page, "request-note-lead", width);
      await expectNoViolations(page, `записка о запросе ${String(width)}`);
    });

    test(`заказ партнёру: шаг без партнёра — без галочки, причина на шаге, ${String(width)} px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "supply@demo.example");
      await spaGoto(page, "/erp/stock/new");
      await expect(
        page.getByRole("heading", { level: 1, name: "Новый заказ партнёру" }),
      ).toBeVisible();
      await page.getByRole("button", { name: /^Строки/ }).click();
      await page.getByRole("button", { name: /^Партнёр и способ/ }).click();
      await expect(page.getByText("Выберите партнёра")).toBeVisible();
      await shot(page, "order-step-needs", width);
      await expectNoViolations(page, `заказ партнёру ${String(width)}`);
    });

    test(`реквизиты: без ИНН шаг «Компания» без галочки, причина названа, ${String(width)} px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/admin/company?tab=details");
      await expect(
        page.getByRole("heading", { level: 2, name: "Реквизиты компании" }),
      ).toBeVisible();
      await page.getByLabel(/^ИНН/).fill("");
      await page.getByRole("button", { name: /^Контакты/ }).click();
      await page.getByRole("button", { name: /^Компания/ }).click();
      await expect(page.getByText("Укажите ИНН — он нужен для счетов")).toBeVisible();
      await shot(page, "details-step-needs", width);
      await expectNoViolations(page, `реквизиты ${String(width)}`);
    });
  }
});
