import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";
import { chooseOrAddAddressee, pickFiles } from "./support/fields";

// Клиенты · Лиды, Клиенты и «Создать заявку» (D1-2b) на MSW: менеджер — лид «Просит КП» → «Создать заявку» с письмом на
// имя директора → заявка ЗВ видна в карточке клиента; двойная отправка — одна заявка; карточка клиента 360° и «Повторить
// отправку в ERP»; 390 px — список карточками, форма листом на весь экран с кнопками внизу; axe (WCAG 2.1 AA); снимки 1440 и
// 390 для PR.

async function expectNoViolations(page: Page, context: string): Promise<void> {
  await waitForMotionEnd(page);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`),
    context,
  ).toEqual([]);
}

const LETTER = {
  name: "pismo-direktoru.pdf",
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.4\n% демо-письмо\n"),
};

test.describe("Лиды → «Создать заявку» → карточка клиента: менеджер", () => {
  test.skip(({ isMobile }) => isMobile, "сценарий на десктопе; 390 — отдельный сценарий @mobile");

  test("лид «Просит КП» → «Создать заявку» с письмом → двойной клик — одна заявка → ЗВ в карточке клиента", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/crm/leads");
    await expect(page.getByRole("heading", { level: 1, name: "Лиды" })).toBeVisible();
    const table = page.getByRole("table", { name: "Лиды" });
    await expect(table.getByRole("link", { name: "Открыть карточку Азиз Демо" })).toBeVisible();
    // Лид из письма: запрос — две строки, а не всё письмо (строка ниже ~100 px)
    const letterRow = table.getByRole("row", { name: /Письмо Демо/ });
    await expect(letterRow.locator(".pf-crm-need-clamp")).toBeVisible();
    expect((await letterRow.boundingBox())?.height ?? 9999).toBeLessThan(110);
    await settledScreenshot(page, "leads");
    await expectNoViolations(page, "список лидов");

    await page.getByRole("tab", { name: "Просят КП" }).click();
    await expect(table.getByRole("link", { name: /^Открыть карточку/ })).toHaveCount(2);

    // Карточка лида в боковом окне
    await table.getByRole("link", { name: "Открыть карточку Азиз Демо" }).click();
    const panel = page.locator("#pf-context-panel");
    await expect(panel.getByRole("heading", { name: "Азиз Демо" })).toBeVisible();
    await expect(panel).toContainText("@aziz_demo");
    await settledScreenshot(page, "lead-card");
    await expectNoViolations(page, "карточка лида");

    // «Создать заявку»: поля из переписки, письмо директору, срочность, «Что произойдёт»
    // окно поверх списка закрывает правые столбцы (ORCHESTRATOR §3 п. 18): сначала скрыть его
    await page.getByRole("button", { name: "Скрыть боковое окно" }).click();
    await page.getByRole("link", { name: "Создать заявку для Азиз Демо" }).click();
    const form = panel.getByRole("form", { name: "Создать заявку" });
    // ЕД-6: компания выбирается; название из переписки стоит в поле серым, «Завести» или существующая
    await expect(form.locator(".ant-select-selection-placeholder")).toHaveText("ООО Демо-Логистик");
    await chooseOrAddAddressee(page, "ООО Демо-Логистик", "Название компании");
    // форма секциями (§4.1a): письмо и срочность — в «Запросе», кнопка — в «Проверке и отправке»
    await form.getByRole("button", { name: /^Запрос/, expanded: false }).click();
    await pickFiles(form.getByLabel("Письмо или файл запроса"), LETTER);
    await expect(form.getByText(`Загружено: ${LETTER.name}`)).toBeVisible();
    await form.getByRole("radio", { name: "Срочная" }).check();
    await settledScreenshot(page, "create-request");
    await expectNoViolations(page, "форма «Создать заявку»");

    // Двойной клик: одна заявка (кнопка занята, ключ формы тот же)
    await form.getByRole("button", { name: /^Проверка и отправка/, expanded: false }).click();
    await form.getByRole("button", { name: /Создать заявку/ }).dblclick();
    await expect(panel.getByText("Заявка создана")).toBeVisible();
    // Б-7: номер, что дальше и «Открыть заявку»
    await expect(panel.getByText("RQ-2026-040")).toBeVisible();
    await expect(panel.getByText("Ждёт резолюции.")).toBeVisible();
    await settledScreenshot(page, "request-done");
    await page.setViewportSize({ width: 1512, height: 900 });
    await settledScreenshot(page, "request-done");
    await page.setViewportSize({ width: 1440, height: 900 });
    await panel.getByRole("link", { name: "Открыть заявку" }).click();

    // Карточка клиента: заявка ЗВ с шкалой и тем, что видит клиент — ровно одна
    await expect(page.getByRole("heading", { level: 1, name: "Контрагенты" })).toBeVisible();
    await expect(panel.getByRole("heading", { name: "ООО Демо-Логистик" })).toBeVisible();
    const requests = panel.getByRole("region", { name: "Заявки и проекты" });
    await expect(requests.getByText("RQ-2026-040")).toBeVisible();
    await expect(requests.getByRole("listitem").filter({ hasText: "RQ-" })).toHaveCount(1);
    await expect(requests).toContainText("В кабинете клиента: «Принято в работу, считаем»");
    await expect(requests.getByText("Срочная")).toBeVisible();
    await settledScreenshot(page, "client-card-new-request");
    await expectNoViolations(page, "карточка клиента с новой заявкой");
  });

  test("«Ждут ответа»: «В заявку» у файла клиента — форма с этим файлом как письмом директору", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/crm/messages?lead=L-2041");
    await page.getByRole("link", { name: "В заявку: Заявка-демо.pdf — письмом директору" }).click();
    const panel = page.locator("#pf-context-panel");
    const form = panel.getByRole("form", { name: "Создать заявку" });
    await form.getByRole("button", { name: /^Запрос/, expanded: false }).click();
    await expect(form.getByText("Загружено: письмо-директору.pdf")).toBeVisible();
    await expectNoViolations(page, "форма с письмом из переписки");
  });

  test("карточка клиента 360°: контакты, переписка, заявки, документы, приглашение; «Повторить отправку»", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/crm/clients");
    await expect(page.getByRole("heading", { level: 1, name: "Контрагенты" })).toBeVisible();
    await page.getByRole("link", { name: "Открыть карточку ООО Рельс-Сервис Демо" }).click();
    const panel = page.locator("#pf-context-panel");
    await expect(panel.getByRole("heading", { name: "ООО Рельс-Сервис Демо" })).toBeVisible();
    await expect(panel.getByRole("region", { name: "Контакты" })).toContainText("основной");
    await expect(panel.getByRole("region", { name: "Документы" })).toContainText(
      "Договор поставки",
    );
    await settledScreenshot(page, "clients");
    await expectNoViolations(page, "карточка клиента 360°");

    const requests = panel.getByRole("region", { name: "Заявки и проекты" });
    await expect(requests).toContainText("Не передана в учёт: нет ответа");
    await requests.getByRole("button", { name: /^Повторить отправку/ }).click();
    await expect(requests.getByText("RQ-2026-040")).toBeVisible();
    await expect(requests.getByRole("button", { name: /^Повторить отправку/ })).toHaveCount(0);
  });
});

// @mobile: проект mobile (Pixel 7, 390) гоняет только сценарии с этим тегом — экраны с адаптивной логикой.
test(
  "390: лиды карточками → «Создать заявку» листом на весь экран с кнопками внизу → карточка клиента листом",
  { tag: "@mobile" },
  async ({ page, isMobile }) => {
    test.skip(!isMobile, "узкий экран — проект mobile");
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/crm/leads");
    const list = page.getByRole("list", { name: "Лиды" });
    await expect(list.getByRole("link", { name: "Открыть карточку Азиз Демо" })).toBeVisible();
    await settledScreenshot(page, "leads");
    await expectNoViolations(page, "лиды 390");

    await list.getByRole("link", { name: "Создать заявку для Азиз Демо" }).click();
    const sheet = page.getByRole("dialog", { name: "Создать заявку" });
    await expect(sheet.locator(".ant-select-selection-placeholder")).toHaveText(
      "ООО Демо-Логистик",
    );
    await chooseOrAddAddressee(page, "ООО Демо-Логистик", "Название компании");
    // Основание заявки обязательно (план 0.4, FR-9)
    const request = sheet.getByRole("button", { name: /^Запрос/, expanded: false });
    if (await request.isVisible()) await request.click();
    await pickFiles(sheet.getByLabel("Письмо или файл запроса"), LETTER);
    await expect(sheet.getByText(`Загружено: ${LETTER.name}`)).toBeVisible();
    await sheet.getByRole("button", { name: /^Проверка и отправка/, expanded: false }).click();
    const submit = sheet.getByRole("button", { name: /Создать заявку/ });
    await expect(submit).toBeVisible();
    await settledScreenshot(page, "create-request");
    await expectNoViolations(page, "форма 390");

    await submit.click();
    await expect(sheet.getByText("Заявка создана")).toBeVisible();
    await expect(sheet.getByText("Ждёт резолюции.")).toBeVisible();
    await settledScreenshot(page, "request-done");
    await sheet.getByRole("link", { name: "Открыть заявку" }).click();
    const card = page.getByRole("dialog", { name: "Карточка контрагента" });
    await expect(card.getByRole("heading", { name: "ООО Демо-Логистик" })).toBeVisible();
    await expect(card.getByText("RQ-2026-040")).toBeVisible();
    const overflow = await page.evaluate(
      "document.documentElement.scrollWidth - document.documentElement.clientWidth",
    );
    expect(overflow).toBe(0);
    await settledScreenshot(page, "client-card");
    await expectNoViolations(page, "карточка клиента 390");
  },
);
