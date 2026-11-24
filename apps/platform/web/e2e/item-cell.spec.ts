import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ЕД-4: позиция в строке любого документа — миниатюра (или значок типа), название и наш артикул одним компонентом
// (`ui-standard.md` §12): номенклатура, расчёт, КП на одобрении, склад, заказ партнёру. Миниатюра — `…/thumbnail?v=`.
const YEAR = String(new Date().getFullYear());

const thumbnail = (page: Page) => page.locator('img[src*="/thumbnail?v="]').first();

test.describe("Позиция в строке документа", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of [1512, 390] as const) {
    test(`${String(width)}: каталог, расчёт, КП, склад и заказ — один вид позиции`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");

      await spaGoto(page, "/erp/catalog");
      await expect(page.getByText("RT-0001").first()).toBeVisible();
      await expect(thumbnail(page)).toBeVisible();
      await settledScreenshot(page, "item-catalog");
      await expectNoViolations(page, `каталог ${String(width)}`);

      await spaGoto(page, `/erp/calc/${encodeURIComponent("ЗВ-2026-097")}`);
      await expect(page.locator(".pf-entity").first()).toBeVisible();
      await settledScreenshot(page, "item-calc");
      await expectNoViolations(page, `расчёт ${String(width)}`);

      await spaGoto(page, `/eds/drafts/${encodeURIComponent("КП-2026/115")}`);
      await expect(page.getByText("Привод стрелочный СП-6").first()).toBeVisible();
      await expect(page.locator(".pf-entity").first()).toBeVisible();
      await settledScreenshot(page, "item-quote");
      await expectNoViolations(page, `КП ${String(width)}`);

      await spaGoto(page, "/erp/stock");
      await expect(page.locator(".pf-entity").first()).toBeVisible();
      await settledScreenshot(page, "item-stock");
      await expectNoViolations(page, `склад ${String(width)}`);

      await spaGoto(page, `/erp/stock/${encodeURIComponent(`ЗП-${YEAR}-029`)}`);
      await expect(page.locator(".pf-entity").first()).toBeVisible();
      await settledScreenshot(page, "item-order");
      await expectNoViolations(page, `заказ ${String(width)}`);

      // ЕД-4 (волна 24): приёмка, отгрузка и поиск по номеру — та же позиция с миниатюрой
      await spaGoto(page, "/erp/stock?view=receipts");
      await expect(page.locator(".pf-entity").first()).toBeVisible();
      await expect(thumbnail(page)).toBeVisible();
      await settledScreenshot(page, "item-receipts");
      await expectNoViolations(page, `приёмка ${String(width)}`);

      await spaGoto(page, "/erp/stock?view=shipments&request=ПР-2026-099");
      await expect(page.locator(".pf-entity").first()).toBeVisible();
      await expect(thumbnail(page)).toBeVisible();
      await settledScreenshot(page, "item-shipments");
      await expectNoViolations(page, `отгрузка ${String(width)}`);
    });
  }
});
