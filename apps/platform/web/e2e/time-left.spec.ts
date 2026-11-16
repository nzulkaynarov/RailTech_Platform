import { expect, test } from "@playwright/test";

import { expectNoViolations } from "./support/axe";
import { loginAndWait, screenshot, spaGoto } from "./support/app";

/**
 * План §3f РЕФ-3: «осталось N дн.» под сроком. Дата зафиксирована до сроков мок-данных (сроки расчёта 28.10–03.11.2026),
 * иначе все они уже просрочены и подписи нет.
 */
test("заявки в расчёте: под сроком — сколько осталось", async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-10-27T10:00:00+05:00"));
  await loginAndWait(page, "supply@demo.example");
  await spaGoto(page, "/erp/requests");
  await expect(page.getByRole("heading", { level: 1, name: "Заявки" })).toBeVisible();
  await expect(page.getByText("осталось 1 дн.").first()).toBeVisible();
  await expect(page.getByText("осталось 7 дн.")).toBeVisible();
  await expectNoViolations(page, "заявки в расчёте");
  await screenshot(page, "calc-requests-time-left");
});
