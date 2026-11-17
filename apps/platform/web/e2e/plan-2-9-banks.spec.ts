import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// План 2.9 на MSW: банк в диалоге счёта компании подсказывает справочник «Банки», выбор подставляет МФО.
// Снимок 1440 с axe — E2E_SCREENSHOT_DIR (docs/screens/plan-2-9).
test("банк из справочника в диалоге счёта", async ({ page }) => {
  test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
  await loginAndWait(page, "admin@demo.example");
  await spaGoto(page, "/admin/company");
  await page.getByRole("button", { name: /Банковские счета/ }).click();
  await page.getByRole("button", { name: "Добавить счёт" }).first().click();
  const dialog = page.getByRole("region", { name: "Новый банковский счёт" });
  await dialog.getByLabel("Банк", { exact: true }).fill("демо");
  await page.getByText("АКБ «Демо Банк» · 00014").click();
  await expect(dialog.getByLabel("МФО")).toHaveValue("00014");
  await waitForMotionEnd(page);
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (dir) await page.screenshot({ path: `${dir}/bank-account-1440.png` });
  await expectNoViolations(page, "банк из справочника");
});
