import { expect, test } from "@playwright/test";
import { pickAddressee } from "./support/fields";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// СУЩ-2.4 на MSW (ADR-0028 п. 4, макет «Контрагент», лист 3): справочник «Бренды» с компанией-изготовителем,
// форма бренда с выбором изготовителя, карточка товара «Бренд · Изготовитель». Снимки 1440 и 390 с axe.
const dir = process.env["E2E_SCREENSHOT_DIR"];

for (const width of [1440, 390] as const) {
  test(`бренды и изготовитель, ${String(width)}`, { tag: "@mobile" }, async ({ page }) => {
    test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/erp/catalog?part=refs");
    await page.locator("label.ant-segmented-item").filter({ hasText: "Бренды" }).click();
    await expect(page.getByRole("link", { name: "АО «Южный Металл»" })).toBeVisible();
    await waitForMotionEnd(page);
    if (dir) await page.screenshot({ path: `${dir}/brands-${String(width)}.png`, fullPage: true });
    await expectNoViolations(page, "бренды");

    await page.getByRole("button", { name: "Изменить: Рельс-Сталь" }).click();
    await expect(page.getByLabel("Изготовитель — компания")).toBeVisible();
    // ЕД-6: изготовитель — любая компания базы; страна подставляется из её карточки
    await pickAddressee(page, "Локо", "Lokotrans GmbH", "Изготовитель — компания");
    await expect(
      page.getByLabel("Страна").locator("xpath=ancestor::div[contains(@class,'ant-select')][1]"),
    ).toContainText("Германия");
    await waitForMotionEnd(page);
    if (dir)
      await page.screenshot({ path: `${dir}/brand-form-${String(width)}.png`, fullPage: true });
    await expectNoViolations(page, "форма бренда");
    await page.keyboard.press("Escape");

    await spaGoto(page, "/erp/catalog");
    await page.getByRole("button", { name: /Открыть позицию Рельс Р65/ }).click();
    const card = page.getByRole("dialog", { name: "Рельс Р65, 25 м" });
    await expect(card.getByRole("link", { name: "АО «Южный Металл»" })).toBeVisible();
    await waitForMotionEnd(page);
    if (dir)
      await page.screenshot({ path: `${dir}/item-maker-${String(width)}.png`, fullPage: true });
    await expectNoViolations(page, "карточка: изготовитель");
  });
}
