import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// План 2.9 на MSW: МФО ищется по коду и названию банка из справочника, название банка подставляется по МФО и не
// правится; МФО не из справочника — предупреждение и банк вручную. Снимки 1440 с axe — E2E_SCREENSHOT_DIR (docs/screens/bank-mfo).
test("банк по МФО из справочника", async ({ page }) => {
  test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
  await loginAndWait(page, "admin@demo.example");
  await spaGoto(page, "/admin/company");
  await page.getByRole("button", { name: /Банковские счета/ }).click();
  await page.getByRole("button", { name: "Добавить счёт" }).first().click();
  const dialog = page.getByRole("region", { name: "Новый банковский счёт" });
  const mfo = dialog.getByLabel("МФО");
  const bank = dialog.getByLabel("Банк", { exact: true });
  await mfo.fill("демо");
  await page.getByText("00014 · АКБ «Демо Банк»").click();
  await expect(mfo).toHaveValue("00014");
  await expect(bank).toHaveValue("АКБ «Демо Банк»");
  await expect(bank).toHaveAttribute("readonly", "");
  await expect(dialog.getByText(/Неверный формат/)).toHaveCount(0);
  await waitForMotionEnd(page);
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (dir) await page.screenshot({ path: `${dir}/bank-mfo-known-1440.png` });
  await expectNoViolations(page, "банк по МФО");

  await mfo.fill("01999");
  await expect(
    dialog.getByText("Нет в справочнике ЦБ — проверьте МФО и впишите банк"),
  ).toBeVisible();
  await expect(bank).toHaveValue("");
  await expect(dialog.getByLabel("SWIFT/BIC — для валютных платежей")).toHaveValue("");
  await expect(bank).not.toHaveAttribute("readonly", "");
  await bank.fill("АКБ «Новый филиал»");
  await waitForMotionEnd(page);
  if (dir) await page.screenshot({ path: `${dir}/bank-mfo-unknown-1440.png` });
  await expectNoViolations(page, "МФО не из справочника");
});
