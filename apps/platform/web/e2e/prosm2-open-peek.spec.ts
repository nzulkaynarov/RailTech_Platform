import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

/**
 * ПРОСМ-2: «Открыть» из списка — тот же просмотр в боковом окне 640, на весь экран с колонкой «О документе»
 * (вид, номер, дата, статус, контрагент). Файл договора проекта (MSW) — четыре страницы с текстом.
 */
const WIDTHS = [1512, 1440, 390] as const;
const dir = process.env["E2E_SCREENSHOT_DIR"];
const PR = (n: number) =>
  `/eds/projects/${encodeURIComponent(`ПР-2026-${String(n).padStart(3, "0")}`)}`;

async function snap(page: Page, name: string): Promise<void> {
  if (dir) await page.screenshot({ path: `${dir}/${name}.png` });
}

for (const width of WIDTHS) {
  test(`файл договора проекта открывается в просмотре на ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 982 });
    await loginAndWait(page, "accountant@demo.example");
    await spaGoto(page, PR(111));
    await expect(page.getByRole("heading", { level: 1, name: "Проект ПР-2026-111" })).toBeVisible();
    await page.getByRole("button", { name: "PDF договора" }).first().click();

    const peek = page.getByRole("dialog", { name: "PDF договора" });
    await expect(peek).toBeVisible();
    await expect(peek.getByTestId("pdf-pages").locator("canvas").first()).toBeVisible();
    await expect(peek.getByText("из 4")).toBeVisible();
    const box = await peek.boundingBox();
    if (width > 767) expect(Math.round(box?.width ?? 0)).toBe(640);
    await expectNoViolations(page, `боковое окно ${String(width)}`);
    await snap(page, `peek-${String(width)}`);

    // на весь экран: справа «О документе»
    await peek.getByTestId("dv-full").click();
    const layer = page.getByRole("dialog", { name: "PDF договора" }).last();
    await expect(layer.getByTestId("dv-layer")).toBeVisible();
    const about = layer.getByRole("complementary", { name: "О документе" });
    await expect(about).toBeVisible();
    await expect(about.getByText("Договор", { exact: true })).toBeVisible();
    await expect(about.getByText("ДОГ-2026/", { exact: false })).toBeVisible();
    await expect(about.getByText("Контрагент")).toBeVisible();
    await expectNoViolations(page, `на весь экран с «О документе» ${String(width)}`);
    await snap(page, `peek-full-${String(width)}`);
  });
}
