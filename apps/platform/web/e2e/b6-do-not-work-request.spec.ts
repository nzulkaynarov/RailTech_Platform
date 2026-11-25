import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// Б-6: у компании с отметкой «Не работать» форма «Создать заявку» говорит об этом сразу и не даёт отправить.
// Снимки 1512, 1440 и 390 и axe — docs/screens/b6.
for (const width of [1512, 1440, 390] as const) {
  test(`заявка для компании с отметкой «Не работать» (${String(width)})`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/crm/clients?client=3&panel=open&tab=card");
    await page.getByRole("button", { name: "Не работать" }).click();
    const dialog = page.getByRole("dialog", { name: "С компанией не работаем" });
    await dialog.getByLabel("Причина").fill("Спор по оплате");
    await dialog.getByRole("button", { name: "Отметить" }).click();
    await expect(dialog).toBeHidden();

    await spaGoto(page, "/crm/clients?client=3&create=1&panel=open&tab=card");
    const form = page.getByRole("form", { name: "Создать заявку" });
    await expect(page.locator(".pf-dnw")).toContainText("С компанией не работаем: Спор по оплате");
    await form.getByRole("button", { name: /^Проверка и отправка/ }).click();
    await expect(
      page.getByText("С компанией не работаем: заявку создать нельзя").first(),
    ).toBeVisible();
    await expect(form.getByRole("button", { name: /Создать заявку/ })).toBeDisabled();
    await settledScreenshot(page, "request-do-not-work");
    await expectNoViolations(page, "заявка для компании с отметкой «Не работать»");
  });
}
