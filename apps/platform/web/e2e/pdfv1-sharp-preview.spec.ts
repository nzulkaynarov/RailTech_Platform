import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto } from "./support/app";

/**
 * Просмотр PDF чёткий на экране 2× (замечание владельца 26.11: «растянуто и размыто, будто скан»): холст рисуется в
 * физических пикселях экрана, а на странице занимает ширину панели. Раньше холст был в CSS-пикселях, и браузер растягивал
 * его вдвое.
 */
test.use({ deviceScaleFactor: 2, viewport: { width: 1512, height: 982 } });

test("PDF на экране 2×: холст вдвое плотнее своей ширины на странице", async ({
  page,
  isMobile,
}) => {
  test.skip(isMobile, "проверка плотности — на десктопе");
  await loginAndWait(page, "engineer@demo.example");
  await spaGoto(page, "/erp/docs");
  await page
    .getByRole("button", { name: /Открыть файл «/ })
    .first()
    .click();
  const canvas = page.getByTestId("pdf-pages").locator("canvas").first();
  await expect(canvas).toBeVisible();
  const size = await canvas.evaluate((node) => {
    const el = node as unknown as { width: number; getBoundingClientRect(): { width: number } };
    return { pixels: el.width, css: el.getBoundingClientRect().width };
  });
  expect(size.css).toBeGreaterThan(200);
  // плотность 2: холст не растягивается браузером
  expect(size.pixels / size.css).toBeGreaterThan(1.9);
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (dir) await page.screenshot({ path: `${dir}/pdf-preview-2x-1512.png` });
});
