import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";
import { chooseOrAddAddressee, openStep } from "./support/fields";

// Б-8: у автора с правом подписи главная кнопка письма — «Подписать и отправить» и ведёт к окну подписания; «Сохранить
// черновик» не уводит из формы. Снимки 1512, 1440 и 390 и axe — docs/screens/b8.
for (const width of [1512, 1440, 390] as const) {
  test(`письмо директора: «Подписать и отправить» (${String(width)})`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/eds/new?type=letter");
    await expect(page.getByRole("heading", { level: 1, name: "Исходящее письмо" })).toBeVisible();
    await page.getByLabel("Тема", { exact: true }).fill("Ответ в банк");
    await chooseOrAddAddressee(page, "ООО «Демо-Банк»");
    await openStep(page, "Текст и вложения");
    const box = page.getByRole("textbox", { name: "Текст", exact: true });
    await box.click();
    await page.keyboard.type("Направляем реквизиты для расчётов.");
    await openStep(page, "Проверка и отправка");

    const primary = page.getByRole("button", { name: /Подписать и отправить$/ });
    await expect(primary).toBeVisible();
    await settledScreenshot(page, "letter-sign-send");
    await expectNoViolations(page, `письмо директора, ${String(width)}`);

    await page.getByRole("button", { name: "Сохранить черновик" }).click();
    await expect(page.getByText("Черновик сохранён")).toBeVisible();
    await expect(page).toHaveURL(/\/eds\/new/);

    await expect(primary).toBeEnabled();
    await primary.click();
    await expect(page).toHaveURL(/sign=1/);
    await expect(page.getByRole("dialog", { name: "Подписание исходящего письма" })).toBeVisible();
    await settledScreenshot(page, "letter-sign-dialog");
  });
}
