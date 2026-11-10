import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// FX-4: бухгалтер подтверждает или отклоняет запрос контрагента на смену реквизитов. axe 0, снимки 1440 и 390.
const WIDTHS = [1440, 390] as const;
const URL_PATH = "/eds/payments?show=bank_changes";
const SHOTS = process.env["E2E_SCREENSHOT_DIR"];

async function shot(page: Page, name: string): Promise<void> {
  await waitForMotionEnd(page);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

for (const width of WIDTHS) {
  test.describe(`смена реквизитов, ${String(width)} px`, { tag: "@mobile" }, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "accountant@demo.example");
    });

    test("запрос на проверке: старые и новые реквизиты, подтвердить и отклонить", async ({
      page,
    }) => {
      await spaGoto(page, URL_PATH);
      const list = page.getByRole("list", { name: "Запросы на смену реквизитов" });
      await expect(list.getByText(/20208000555566667777/)).toBeVisible();
      await expect(list.getByRole("button", { name: "Подтвердить" })).toBeVisible();
      await shot(page, `queue-${String(width)}`);
      await expectNoViolations(page, "очередь");

      await list.getByRole("button", { name: "Отклонить" }).click();
      const dialog = page.getByRole("dialog");
      await waitForMotionEnd(page);
      await shot(page, `reject-dialog-${String(width)}`);
      await expectNoViolations(page, "отклонение");
      await dialog.getByRole("button", { name: "Отмена" }).click();

      await list.getByRole("button", { name: "Подтвердить" }).click();
      const approve = page.getByRole("dialog");
      await shot(page, `approve-dialog-${String(width)}`);
      await approve.getByRole("button", { name: "Подтвердить" }).click();

      await expect(page.getByText("Запросов на проверке нет")).toBeVisible();
    });
  });
}
