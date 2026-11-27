import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ТЕСТ-2 на MSW: «Показывать тестовые» в профиле — по умолчанию выключено, тестовой заявки в «Заявках» нет; включили — она
// там с меткой «Тестовая»; выключили — снова скрыта. Снимки 1440 и 390 с axe.
const dir = process.env["E2E_SCREENSHOT_DIR"];
const TEST_REQUEST = "ЗВ-2026-190";

for (const width of [1440, 390] as const) {
  test(
    `«Показывать тестовые»: профиль → «Заявки» с меткой, ${String(width)}`,
    {
      tag: "@mobile",
    },
    async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "supply@demo.example");

      // 1. по умолчанию тестовой заявки в «Заявках» нет
      await spaGoto(page, "/erp/requests");
      await expect(page.getByText("ЗВ-2026-101").first()).toBeVisible();
      await expect(page.getByText(TEST_REQUEST)).toHaveCount(0);

      // 2. профиль: включить «Показывать тестовые компании и их документы»
      await spaGoto(page, "/me");
      const toggle = page.getByRole("switch", { name: "Показывать тестовые компании и их документы" });
      await expect(toggle).not.toBeChecked();
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/profile-off-${String(width)}.png`, fullPage: true });
      await toggle.click();
      await expect(toggle).toBeChecked();
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/profile-on-${String(width)}.png`, fullPage: true });
      await expectNoViolations(page, "«Показывать тестовые»: профиль");

      // 3. в «Заявках» тестовая заявка видна, с меткой «Тестовая»
      await spaGoto(page, "/erp/requests");
      await expect(page.getByText(TEST_REQUEST).first()).toBeVisible();
      await expect(page.locator(".ant-tag", { hasText: "Тестовая" }).first()).toBeVisible();
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/requests-${String(width)}.png`, fullPage: true });
      await expectNoViolations(page, "«Показывать тестовые»: «Заявки» с меткой");

      // 4. выключили — скрыта
      await spaGoto(page, "/me");
      await page
        .getByRole("switch", { name: "Показывать тестовые компании и их документы" })
        .click();
      await expect(
        page.getByRole("switch", { name: "Показывать тестовые компании и их документы" }),
      ).not.toBeChecked();
      await spaGoto(page, "/erp/requests");
      await expect(page.getByText("ЗВ-2026-101").first()).toBeVisible();
      await expect(page.getByText(TEST_REQUEST)).toHaveCount(0);
    },
  );
}
