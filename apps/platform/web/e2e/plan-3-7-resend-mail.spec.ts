import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// План 3.7 (MAIL-2) на MSW: «Отправить ещё раз» из текста отправленного письма — новое письмо в очереди;
// у приглашения (письмо со входом) текста нет и кнопки нет. Снимок 1440 с axe — E2E_SCREENSHOT_DIR (docs/screens/plan-3-7).
test("отправить письмо ещё раз", async ({ page }) => {
  test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
  await page.setViewportSize({ width: 1440, height: 900 });
  await loginAndWait(page, "registrar@demo.example");
  await spaGoto(page, "/eds/mail?tab=sent");
  const table = page.getByRole("table", { name: "Отправленные письма" });
  await expect(table).toBeVisible();

  await page.getByRole("button", { name: /Приглашение в кабинет клиента/ }).click();
  const invite = page.getByRole("dialog", { name: /Приглашение в кабинет/ });
  await expect(invite.getByText("Текст письма уже не хранится.")).toBeVisible();
  await expect(invite.getByRole("button", { name: "Отправить ещё раз" })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(invite).toBeHidden();

  await page.getByRole("button", { name: /Ответ на требование о пояснениях/ }).click();
  const drawer = page.getByRole("dialog", { name: /Ответ на требование/ });
  await expect(drawer.getByText(/Направляем ответ на требование/)).toBeVisible();
  await waitForMotionEnd(page);
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (dir) await page.screenshot({ path: `${dir}/resend-1440.png` });
  await expectNoViolations(page, "текст письма с «Отправить ещё раз»");
  await drawer.getByRole("button", { name: "Отправить ещё раз" }).click();
  await expect(
    page.getByText("Письмо для gni-mirabad@example.uz поставлено в очередь"),
  ).toBeVisible();
  await expect(table.getByRole("row").filter({ hasText: "gni-mirabad@example.uz" })).toHaveCount(2);
  await expect(table.getByText("Отправляется")).toBeVisible();
});
