import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ЕД-6, PR-4 на MSW: подписант письма — выбор из держателей права подписи (должность из справочника, правится для «и. о.»);
// «Кто замещает» — тот же выбор по всем активным сотрудникам. Снимки 1440 и 390 с axe.
const dir = process.env["E2E_SCREENSHOT_DIR"];

for (const width of [1440, 390] as const) {
  test(`письмо: подписант выбором, ${String(width)}`, { tag: "@mobile" }, async ({ page }) => {
    test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/eds/new?type=letter");
    await page.getByRole("button", { name: /Согласование и подпись/ }).click();

    const signer = page.getByRole("combobox", { name: "Подписант" });
    await signer.click();
    await page.locator(".ant-select-item-option").filter({ hasText: "Демо Директоров" }).click();
    await expect(page.getByLabel("Должность подписанта")).toHaveAttribute(
      "placeholder",
      "Директор",
    );
    await page.getByLabel("Должность подписанта").fill("И. о. директора");
    await waitForMotionEnd(page);
    if (dir) await page.screenshot({ path: `${dir}/letter-signer-${String(width)}.png` });
    await expectNoViolations(page, "подписант письма");
  });

  test(
    `«Кто замещает»: все активные сотрудники с поиском, ${String(width)}`,
    { tag: "@mobile" },
    async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/me");
      const deputy = page.getByRole("region", { name: "Замещение" });
      const who = deputy.getByRole("combobox", { name: "Кто замещает" });
      await who.click();
      await who.fill("снабж");
      await expect(
        page.locator(".ant-select-item-option").filter({ hasText: "Демо Снабженцев" }),
      ).toBeVisible();
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/deputy-picker-${String(width)}.png` });
      await deputy.getByTestId("deputy-sentence").click();
      await expect(page.locator(".ant-select-dropdown:visible")).toHaveCount(0);
      await expectNoViolations(page, "кто замещает");
    },
  );
}
