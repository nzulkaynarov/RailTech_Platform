import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { fillDate } from "./support/fields";

// L0-3 волны L0 «Прослеживаемость-минимум» (ADR-0021) на MSW, 1440 и 390 px, axe WCAG 2.1 AA:
// — учёт единиц — данные категории: «Электрооборудование» серийная с документом соответствия;
// — приёмка ЗП с серийными (вставка столбцом) и сертификатом: поля появляются только у такой строки;
// — отгрузка по проекту — только выбранные свободные серийные; номер виден в накладной;
// — «Склад · Прослеживаемость»: поиск по серийному показывает «откуда» (поставщик, заказ, изготовитель, документ) и «куда».
// Снимки — в E2E_SCREENSHOT_DIR (docs/screens/l0-3), если он задан.
const WIDTHS = [1440, 390] as const;
const YEAR = String(new Date().getFullYear());
const ORDER = `ЗП-${YEAR}-028`;
const MOTOR = "Электродвигатель асинхронный АИР-100";
const VALID = `${String(new Date().getFullYear() + 1)}-06-30`;

async function expectNoViolations(page: Page, context: string): Promise<void> {
  await waitForMotionEnd(page);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`),
    context,
  ).toEqual([]);
}

async function shot(page: Page, name: string, fullPage = true): Promise<void> {
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (!dir) return;
  await expect(page.locator(".ant-message-notice")).toHaveCount(0, { timeout: 15_000 });
  await waitForMotionEnd(page);
  await page.waitForTimeout(400);
  const width = page.viewportSize()?.width ?? 0;
  await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage });
}

test.describe("L0-3: прослеживаемость", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`категория: учёт единиц и документ соответствия, ${String(width)} px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/admin/company?tab=categories");
      await expect(page.getByText("Электрооборудование · серийный · документ")).toBeVisible();
      await page.getByRole("button", { name: "Изменить: Электрооборудование" }).click();
      const dialog = page.getByRole("dialog", { name: "Изменить категорию" });
      await expect(dialog.getByText("Серийный номер каждой единицы")).toBeVisible();
      await expect(
        dialog.getByRole("checkbox", { name: /Нужен документ соответствия/ }),
      ).toBeChecked();
      await expectNoViolations(page, `категория ${String(width)}`);
      await shot(page, "l0-3-category", false);
    });

    test(`приёмка с серийными → отгрузка → поиск, ${String(width)} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "supply@demo.example");
      await spaGoto(page, `/erp/stock/${encodeURIComponent(ORDER)}`);
      await page.getByRole("button", { name: "Принять товар" }).click();
      const modal = page.getByRole("dialog", { name: `Принять товар по заказу ${ORDER}` });
      const fields = modal.getByRole("group", { name: `Номера и документ: «${MOTOR}»` });
      await fields.getByLabel("Серийные номера — по одному в строке").fill("ENG-0001\nENG-0002");
      await expect(fields.getByText("Введено 2 из 2")).toBeVisible();
      await fields.getByLabel("№ сертификата или декларации").fill("ЕАЭС RU С-UZ.ДЕМО.В.00042");
      await fillDate(fields.getByLabel("Действует до"), VALID);
      await expectNoViolations(page, `приёмка ${String(width)}`);
      await shot(page, "l0-3-receipt", false);
      await modal.getByRole("button", { name: "Принять" }).click();
      await expect(modal).toHaveCount(0);

      await spaGoto(page, "/erp/stock?view=shipments");
      await page.getByRole("searchbox", { name: "Номер проекта" }).fill("ПР-2026-099");
      await page.getByRole("button", { name: "Найти резервы" }).click();
      await page.getByRole("spinbutton", { name: `Отгрузить, «${MOTOR}»` }).fill("1");
      await page
        .getByRole("spinbutton", { name: "Отгрузить, «Скрепление рельсовое КБ-65»" })
        .fill("0");
      await page.getByRole("checkbox", { name: "ENG-0002" }).check();
      await expectNoViolations(page, `отгрузка ${String(width)}`);
      await shot(page, "l0-3-shipment");
      await page.getByRole("button", { name: "Отгрузить" }).click();
      await expect(page.getByText(/Отгружено, накладная ОТГ-\d{4}-001/)).toBeVisible();

      await spaGoto(page, "/erp/stock?view=trace&q=ENG-0002");
      const card = page.locator(".ant-card", {
        has: page.getByRole("heading", { name: /Серийный ENG-0002/ }),
      });
      await expect(card.getByRole("region", { name: "Откуда" }).getByText(ORDER)).toBeVisible();
      await expect(
        card.getByRole("region", { name: "Куда" }).getByText(/ОТГ-\d{4}-001/),
      ).toBeVisible();
      await expectNoViolations(page, `прослеживаемость ${String(width)}`);
      await shot(page, "l0-3-trace");
    });
  }
});
