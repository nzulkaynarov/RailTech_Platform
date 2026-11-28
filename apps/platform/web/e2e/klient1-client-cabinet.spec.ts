import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { chooseOrAddAddressee, pickFiles } from "./support/fields";

// КЛИЕНТ-1 на MSW: лид → «Создать заявку» → карточка лида показывает «Заявка … создана», главная «Создать заявку» ушла,
// «Ещё одна заявка» — вторая; в карточке клиента у контакта переключатель «Может подтверждать» (право решает сервер).

const LETTER = {
  name: "pismo-direktoru.pdf",
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.4\n% демо-письмо\n"),
};
const LONG_NAME =
  "Ташкентский машиностроительный завод имени Узбекского объединения тяжёлого оборудования";

for (const width of [1512, 390]) {
  test(`лид с заявкой: «Заявка … создана», без главной «Создать заявку» (${String(width)})`, async ({
    page,
    isMobile,
  }) => {
    test.skip(isMobile, "ширину задаёт сам спек");
    await page.setViewportSize({ width, height: width === 390 ? 844 : 982 });
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/crm/leads?lead=L-2041&panel=open&tab=card");
    const panel =
      width === 390 ? page.getByRole("dialog").last() : page.locator("#pf-context-panel");
    await expect(panel.getByRole("heading", { name: "Азиз Демо" })).toBeVisible();
    await expect(panel.getByRole("link", { name: "Создать заявку", exact: true })).toBeVisible();

    await panel.getByRole("link", { name: "Создать заявку", exact: true }).click();
    const form = (
      width === 390 ? page.getByRole("dialog", { name: "Создать заявку" }) : panel
    ).getByRole("form", { name: "Создать заявку" });
    await chooseOrAddAddressee(page, LONG_NAME, "Название компании");
    await form.getByRole("button", { name: /^Запрос/, expanded: false }).click();
    await pickFiles(form.getByLabel("Письмо или файл запроса"), LETTER);
    await form.getByRole("button", { name: /^Проверка и отправка/, expanded: false }).click();
    await form.getByRole("button", { name: /Создать заявку/ }).click();
    await expect(panel.getByText("Заявка создана")).toBeVisible();

    await spaGoto(page, "/crm/leads?lead=L-2041&panel=open&tab=card");
    const request = panel.getByTestId("lead-request");
    await expect(request).toContainText("Заявка RQ-2026-040 создана");
    await expect(request.getByRole("link", { name: "Открыть заявку" })).toBeVisible();
    await expect(panel.getByRole("link", { name: "Создать заявку", exact: true })).toHaveCount(0);
    await expect(panel.getByRole("link", { name: "Ещё одна заявка" })).toBeVisible();
    await expect(panel).not.toContainText("both");
    await settledScreenshot(page, "klient1-lead-after-request");
  });

  test(`карточка клиента: «Может подтверждать» у каждого контакта (${String(width)})`, async ({
    page,
    isMobile,
  }) => {
    test.skip(isMobile, "ширину задаёт сам спек");
    await page.setViewportSize({ width, height: width === 390 ? 844 : 982 });
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/crm/clients/3?panel=open&tab=card");
    const panel =
      width === 390 ? page.getByRole("dialog").last() : page.locator("#pf-context-panel");
    await expect(panel.getByRole("heading", { name: "ООО Рельс-Сервис Демо" })).toBeVisible();
    await panel.getByRole("tab", { name: "Обзор" }).click();
    const switches = panel.getByRole("switch");
    await expect(switches.first()).toBeChecked();
    await expect(switches.nth(1)).not.toBeChecked();
    await settledScreenshot(page, "klient1-client-contact-right-before");
    await switches.nth(1).click();
    await expect(switches.nth(1)).toBeChecked();
    await settledScreenshot(page, "klient1-client-contact-right");
  });
}
