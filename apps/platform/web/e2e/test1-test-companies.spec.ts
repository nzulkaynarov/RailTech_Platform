import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ТЕСТ-1 на MSW: «Отметить как тестовую» в карточке контрагента, нейтральная метка «Тестовая», компания уходит из рабочего
// списка и видна на вкладке «Тестовые», «Снять отметку» возвращает её. Снимки 1440 и 390 с axe.
const dir = process.env["E2E_SCREENSHOT_DIR"];

for (const width of [1440, 390] as const) {
  test(
    `«Тестовая»: отметка, вкладка «Тестовые», снятие, ${String(width)}`,
    {
      tag: "@mobile",
    },
    async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "manager@demo.example");

      // 1. карточка клиента: действие «Отметить как тестовую»; у компании есть открытая заявка — один вопрос
      await spaGoto(page, "/crm/clients/3?panel=open&tab=card");
      const name = "ООО Рельс-Сервис Демо";
      await page.getByRole("button", { name: "Отметить как тестовую" }).click();
      const ask = page.getByRole("dialog", { name: "Отметить как тестовую?" });
      await expect(ask).toContainText("открытых заявок");
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/ask-${String(width)}.png` });
      await expectNoViolations(page, "«Тестовая»: вопрос про открытые заявки");
      await ask.getByRole("button", { name: "Отметить" }).click();
      await expect(ask).toBeHidden();

      // 2. нейтральная метка и «Снять отметку» в карточке
      await expect(page.locator(".ant-tag", { hasText: "Тестовая" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Снять отметку" })).toBeVisible();
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/card-${String(width)}.png`, fullPage: true });
      await expectNoViolations(page, "«Тестовая»: карточка контрагента");

      // 3. рабочий список без неё
      await spaGoto(page, "/crm/clients");
      await expect(page.getByRole("link", { name: /Открыть карточку/ }).first()).toBeVisible();
      await expect(
        page.getByRole("link", { name: new RegExp(`Открыть карточку ${name}`) }),
      ).toHaveCount(0);

      // 4. вкладка «Тестовые»: только она
      await spaGoto(page, "/crm/clients?kind=test");
      await expect(
        page.getByRole("link", { name: new RegExp(`Открыть карточку ${name}`) }),
      ).toBeVisible();
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/tab-${String(width)}.png`, fullPage: true });
      await expectNoViolations(page, "«Тестовая»: вкладка «Тестовые»");

      // 5. «Снять отметку» — без вопроса, компания возвращается в рабочий список
      await page.getByRole("link", { name: new RegExp(`Открыть карточку ${name}`) }).click();
      await page.getByRole("button", { name: "Снять отметку" }).click();
      await expect(page.getByRole("button", { name: "Отметить как тестовую" })).toBeVisible();
      await spaGoto(page, "/crm/clients");
      await expect(
        page.getByRole("link", { name: new RegExp(`Открыть карточку ${name}`) }),
      ).toBeVisible();
    },
  );
}
