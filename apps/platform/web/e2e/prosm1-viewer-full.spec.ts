import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

/**
 * ПРОСМ-1: единый просмотр документа — панель и слой «на весь экран». Образец договора из четырёх страниц (MSW) открыт в
 * «Реквизиты и бланк»: поиск по тексту со счётчиком, выделение текста, масштаб, страницы, слой с адресом
 * `?view=full&page=N` (перезагрузка, «Назад», Esc с возвратом фокуса), миниатюры. axe — 1512, 1440, 390.
 */
const WIDTHS = [1512, 1440, 390] as const;
const dir = process.env["E2E_SCREENSHOT_DIR"];

async function openSample(page: Page): Promise<void> {
  await loginAndWait(page, "director@demo.example");
  await spaGoto(page, "/admin/company?tab=brand");
  await page.locator(".ant-segmented-item-label", { hasText: "Договор" }).click();
  await expect(page.getByTestId("pdf-pages").locator("canvas").first()).toBeVisible();
  await expect(page.getByTestId("dv-panel").first().getByText("из 4")).toBeVisible();
}

async function snap(page: Page, name: string): Promise<void> {
  if (dir) await page.screenshot({ path: `${dir}/${name}.png` });
}

test.describe("ПРОСМ-1: просмотр документа на весь экран", () => {
  for (const width of WIDTHS) {
    test(`сценарий на ${String(width)} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 982 });
      await openSample(page);
      const phone = width === 390;
      const panel = page.getByTestId("dv-panel").first();

      if (!phone) {
        // поиск по тексту образца договора: слово находится, счётчик виден
        await panel.getByRole("textbox", { name: "Поиск по тексту" }).fill("срок");
        await expect(panel.getByRole("status").filter({ hasText: /^1 из \d+$/ })).toBeVisible();
        await panel.getByRole("button", { name: "Следующее совпадение" }).click();
        await expect(panel.getByRole("status").filter({ hasText: /^2 из \d+$/ })).toBeVisible();
        await panel.getByRole("textbox", { name: "Поиск по тексту" }).clear();

        // выделение текста: поверх холста есть настоящий текстовый слой
        const word = page.locator(".textLayer span", { hasText: "Поставщик" }).first();
        await expect(word).toBeVisible();
        await word.click({ clickCount: 3 });
        const selected = String(await page.evaluate(`window.getSelection()?.toString() ?? ""`));
        expect(selected.length).toBeGreaterThan(2);

        // масштаб
        await panel.getByText("По ширине", { exact: true }).click();
        const before = await panel.locator(".pf-dv-percent").innerText();
        await panel.getByRole("button", { name: "Увеличить" }).click();
        await expect(panel.locator(".pf-dv-percent")).not.toHaveText(before);
        await panel.getByText("По ширине", { exact: true }).click();
        await expect(panel.locator(".pf-dv-percent")).toHaveText(before);
        await expectNoViolations(page, `панель ${String(width)}`);
        await snap(page, `panel-${String(width)}`);
        const button = panel.getByRole("button", { name: "На весь экран" });
        await button.click();
      } else {
        // на телефоне нажатие на лист открывает слой сразу
        await expectNoViolations(page, "панель 390");
        await snap(page, "panel-390");
        await page.getByTestId("pdf-pages").click({ position: { x: 40, y: 80 } });
      }

      const layer = page.getByRole("dialog", { name: /Образец: Договор/ });
      await expect(layer).toBeVisible();
      await expect(page).toHaveURL(/[?&]view=full&page=1/);
      await expect(layer.getByTestId("pdf-pages").locator("canvas").first()).toBeVisible();

      // страницы: миниатюра ведёт на страницу, адрес держит её
      if (!phone) {
        await expect(layer.getByRole("navigation", { name: "Страницы" })).toBeVisible();
        await layer.getByRole("button", { name: "Страница 3" }).click();
        await expect(page).toHaveURL(/page=3/);
        await expect(layer.getByRole("spinbutton", { name: "Страница" })).toHaveValue("3");
      } else {
        await expect(layer.getByRole("navigation", { name: "Страницы" })).toHaveCount(0);
        await layer.getByRole("spinbutton", { name: "Страница" }).fill("2");
        await layer.getByRole("spinbutton", { name: "Страница" }).press("Enter");
        await expect(page).toHaveURL(/page=2/);
      }
      await expectNoViolations(page, `на весь экран ${String(width)}`);
      await snap(page, `full-${String(width)}`);

      // адрес переживает перезагрузку: слой открыт на той же странице
      await page.reload({ waitUntil: "domcontentloaded" });
      // после перезагрузки образец — по умолчанию (КП): слой открыт тем же адресом, на той же странице
      const again = page.getByRole("dialog", { name: /Образец:/ });
      await expect(again).toBeVisible();
      await expect(again.getByRole("spinbutton", { name: "Страница" })).toHaveValue(
        phone ? "2" : "3",
      );
    });
  }

  test("Esc сворачивает слой и возвращает фокус на кнопку; «Назад» тоже сворачивает", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1512, height: 982 });
    await openSample(page);
    const button = page
      .getByTestId("dv-panel")
      .first()
      .getByRole("button", { name: "На весь экран" });
    await button.focus();
    await page.keyboard.press("Enter");
    const layer = page.getByRole("dialog", { name: /Образец: Договор/ });
    await expect(layer).toBeVisible();
    // фокус ушёл в слой
    await expect(layer.getByRole("button", { name: /Свернуть/ })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(layer).toBeHidden();
    await expect(page).not.toHaveURL(/view=full/);
    await expect(button).toBeFocused();

    await button.click();
    await expect(layer).toBeVisible();
    await page.goBack();
    await expect(layer).toBeHidden();
    await expect(page).not.toHaveURL(/view=full/);
  });

  test("в слое: клавиши масштаба и поиск по Ctrl F", async ({ page }) => {
    await page.setViewportSize({ width: 1512, height: 982 });
    await openSample(page);
    await page
      .getByTestId("dv-panel")
      .first()
      .getByRole("button", { name: "На весь экран" })
      .click();
    const layer = page.getByRole("dialog", { name: /Образец: Договор/ });
    await expect(layer).toBeVisible();
    const percent = layer.locator(".pf-dv-percent");
    await expect(layer.getByText("из 4")).toBeVisible();
    await layer.getByTestId("pdf-pages").focus();
    await page.keyboard.press("0");
    const start = await percent.innerText();
    await page.keyboard.press("+");
    await expect(percent).not.toHaveText(start);
    await page.keyboard.press("0");
    await expect(percent).toHaveText(start);
    await page.keyboard.press("Control+f");
    await expect(layer.getByRole("textbox", { name: "Поиск по тексту" })).toBeFocused();
    await page.keyboard.type("гарантийный");
    await expect(layer.getByRole("status").filter({ hasText: /^1 из \d+$/ })).toBeVisible();
    await snap(page, "full-search-1512");
  });
});
