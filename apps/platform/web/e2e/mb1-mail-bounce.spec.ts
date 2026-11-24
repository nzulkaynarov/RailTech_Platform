import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// mb1: почтовые серверы возвращают письма (отчёты о недоставке) — карточка лида и контакт клиента говорят «Письма на
// этот адрес не доходят» с причиной словами и датой; журнал почты показывает недоставленное письмо; «Новый лид» с
// несуществующим почтовым доменом — ошибка у поля почты. Снимки 1440 и 390, axe WCAG 2.1 AA.
const WIDTHS = [1440, 390] as const;

async function noHorizontalScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    "document.documentElement.scrollWidth - document.documentElement.clientWidth",
  );
  expect(overflow).toBe(0);
}

for (const width of WIDTHS) {
  test.describe(`Недоставленная почта, ${String(width)} px`, () => {
    test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

    test("карточка лида: «Письма на этот адрес не доходят: причина · дата»", async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/crm/leads");
      await page.getByRole("link", { name: "Открыть карточку Шахноза Демо" }).click();
      await expect(
        page.getByText(
          /Письма на этот адрес не доходят: такого почтового домена нет · \d{2}\.\d{2}\.\d{4}/,
        ),
      ).toBeVisible();
      await expectNoViolations(page, "карточка лида");
      await noHorizontalScroll(page);
      await settledScreenshot(page, "lead-card");
    });

    test("карточка клиента: у контакта с возвращающимся адресом та же строка", async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/crm/clients");
      await page.getByRole("link", { name: "Открыть карточку ООО Рельс-Сервис Демо" }).click();
      await expect(
        page
          .getByRole("region", { name: "Контакты" })
          .getByText(/Письма на этот адрес не доходят: такого ящика нет/),
      ).toBeVisible();
      await expectNoViolations(page, "карточка клиента");
      await settledScreenshot(page, "client-contact");
    });

    test("«Новый лид»: почтового домена нет — ошибка у поля почты", async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "manager@demo.example");
      if (width < 600) await page.getByRole("button", { name: "Меню" }).click();
      await page.getByRole("button", { name: "Создать", exact: true }).click();
      await page
        .getByRole("dialog", { name: "Создать" })
        .getByRole("link", { name: /^Лид/ })
        .click();
      const form = page.getByRole("form", { name: "Новый лид" });
      await form.getByText("Письмо", { exact: true }).click();
      await form.getByLabel("Имя").fill("Азиз Каримов");
      await form.getByLabel("Почта").fill("aziz@tvorog.invalid");
      await form.getByLabel("Что нужно").fill("Колёсные пары, 10 шт.");
      await form.getByRole("button", { name: "Создать лид" }).click();
      await expect(
        form.getByText("Проверьте адрес почты — такого почтового домена нет"),
      ).toBeVisible();
      await expectNoViolations(page, "новый лид");
      await settledScreenshot(page, "new-lead-bad-domain");
    });

    test("журнал почты: письмо, которое сервер принял и вернул, — «Не дошло: причина»", async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin/mail");
      await expect(page.getByRole("heading", { level: 1, name: "Почта" })).toBeVisible();
      await expect(
        page.getByText(/Не дошло: такого почтового домена нет · \d{2}\.\d{2}\.\d{4}/),
      ).toBeVisible();
      await page.getByText(/Не дошло:/).scrollIntoViewIfNeeded();
      await expectNoViolations(page, "журнал почты");
      await settledScreenshot(page, "mail-log-bounce");
    });
  });
}
