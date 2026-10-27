import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// Клиенты · Ждут ответа (D1-1) на MSW: сценарий менеджера целиком — очередь передач с таймером SLA → «Забрать» → ответ «От себя»
// → «Telegram не ответил» и «Повторить» (текст в поле, без дубля) → «Заметка команде» → шаблон → «Подсказать ответ» → новое
// сообщение клиента приходит подсказкой потока без перезагрузки → «Показать раньше»; директор — только чтение; 390 px —
// список, диалог на весь экран и карточка лида листом с кнопками внизу; axe (WCAG 2.1 AA); снимки 1440 и 390 для PR.

const TELEGRAM_DOWN = "rt-pf-mock-telegram-down";
const INBOX_EMPTY = "rt-pf-mock-inbox-empty";

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

async function setFlag(page: Page, key: string, on: boolean): Promise<void> {
  await page.evaluate(
    on
      ? `window.localStorage.setItem(${JSON.stringify(key)}, "1")`
      : `window.localStorage.removeItem(${JSON.stringify(key)})`,
  );
}

async function openMessages(page: Page, query = ""): Promise<void> {
  await spaGoto(page, `/crm/messages${query}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

function inbox(page: Page) {
  return page.getByRole("navigation", { name: "Диалоги, которые ждут ответа" });
}

function composerField(page: Page) {
  return page.getByLabel(/^(Сообщение клиенту|Заметка для команды)$/);
}

test.describe("Ждут ответа: менеджер", () => {
  test.skip(({ isMobile }) => isMobile, "сценарий на десктопе; 390 — отдельный сценарий @mobile");

  test("передача → «Забрать» → ответ, ошибка и «Повторить» → заметка → шаблон → подсказка → живое сообщение", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await openMessages(page);

    const list = inbox(page);
    await expect(list.getByRole("heading", { name: "Передачи от бота · 2" })).toBeVisible();
    await expect(list.getByText("ждёт 12 мин")).toBeVisible();
    await expect(list.getByText("ждёт 40 мин · срок прошёл")).toBeVisible();
    await expect(list.getByText("Срочно")).toBeVisible();
    await settledScreenshot(page, "list");
    await expectNoViolations(page, "очередь");

    // «Забрать»: лид у менеджера, бот молчит
    await list.getByRole("button", { name: "Забрать: Азиз Демо" }).click();
    await expect(page.getByText("Лид у вас. Бот молчит, пока вы в диалоге.")).toBeVisible();
    await list.getByRole("link", { name: /^Азиз Демо/ }).click();
    await expect(page.getByRole("heading", { level: 2, name: "Азиз Демо" })).toBeVisible();
    await expect(page.getByText("L-2041 · Telegram · Диалог ведёте вы")).toBeVisible();
    await expect(page.getByRole("region", { name: "Записка передачи" })).toContainText(
      "Уточнить объём и прислать КП сегодня",
    );
    await expect(page.getByRole("link", { name: "Скачать Заявка-демо.pdf" })).toBeVisible();
    await expect(page.locator("#pf-context-panel")).toContainText("@aziz_demo");
    await expect(page.getByText("Уйдёт клиенту в Telegram")).toBeVisible();
    await settledScreenshot(page, "dialog");
    await expectNoViolations(page, "диалог");

    // «От себя»: Telegram не ответил → текст в поле, «Повторить» без дубля
    await setFlag(page, TELEGRAM_DOWN, true);
    await composerField(page).fill("Добрый день! Цена на 40 т — в КП сегодня до 17:00.");
    await page.getByRole("button", { name: "Отправить" }).click();
    const alert = page
      .getByRole("alert")
      .filter({ hasText: "Не отправлено: Telegram не ответил." });
    await expect(alert).toBeVisible();
    await expect(composerField(page)).toHaveValue(
      "Добрый день! Цена на 40 т — в КП сегодня до 17:00.",
    );
    await settledScreenshot(page, "send-error");
    await expectNoViolations(page, "ошибка отправки");
    await setFlag(page, TELEGRAM_DOWN, false);
    await alert.getByRole("button", { name: "Повторить" }).click();
    const sent = page.locator(".pf-msg-bubble", {
      hasText: "Добрый день! Цена на 40 т — в КП сегодня до 17:00.",
    });
    await expect(sent).toHaveCount(1);
    await expect(composerField(page)).toHaveValue("");

    // «Заметка команде»: клиенту не уходит
    await page.getByText("Заметка команде", { exact: true }).first().click();
    await expect(page.getByText("Увидит только команда")).toBeVisible();
    await composerField(page).fill("Клиент сравнивает с конкурентом — держать срок КП");
    await page.getByRole("button", { name: "Сохранить заметку" }).click();
    await expect(
      page.locator(".pf-msg-item--note", { hasText: "Клиент сравнивает с конкурентом" }),
    ).toBeVisible();

    // Шаблон и «Подсказать ответ» — в поле, отправляет человек
    await page.getByText("От себя", { exact: true }).click();
    await page.getByRole("combobox", { name: "Шаблон ответа" }).click();
    await page.getByTitle("Пришлю КП сегодня").click();
    await expect(composerField(page)).toHaveValue(
      /^Азиз Демо, добрый день! Пришлю коммерческое предложение/,
    );
    await composerField(page).fill("");
    await page.getByRole("button", { name: "Подсказать ответ" }).click();
    await expect(composerField(page)).toHaveValue(/Подготовлю коммерческое предложение/);
    await expect(page.getByText("Подсказка в поле — проверьте и отправьте сами")).toBeVisible();

    // Клиент пишет в бота: подсказка потока BFF → лента обновляется без перезагрузки и без опроса
    expect(
      await page.evaluate(
        "typeof window.__rtMockStreamCount === 'function' && window.__rtMockStreamCount()",
      ),
    ).toBeGreaterThan(0);
    await page.evaluate(
      `window.__rtMockClientWrites("L-2041", "А доставка до станции входит в цену?")`,
    );
    await expect(
      page.locator(".pf-msg-bubble", { hasText: "А доставка до станции входит в цену?" }),
    ).toBeVisible({ timeout: 2_000 });

    // История: «Показать раньше»
    await page.getByRole("button", { name: "Показать раньше" }).click();
    await expect(
      page.locator(".pf-msg-bubble", { hasText: /^Ранее: вопрос о поставке, часть 1$/ }),
    ).toBeVisible();
  });

  test("пустая очередь — «Все передачи разобраны»", async ({ page }) => {
    await loginAndWait(page, "manager@demo.example");
    await setFlag(page, INBOX_EMPTY, true);
    await openMessages(page);
    await expect(page.getByRole("heading", { name: "Все передачи разобраны" })).toBeVisible();
    await expect(
      page.getByText("Бот отвечает сам, пока клиент не попросит человека."),
    ).toBeVisible();
    await settledScreenshot(page, "empty");
    await expectNoViolations(page, "пустое состояние");
  });

  test("директор видит очередь и переписку только для чтения", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await openMessages(page, "?lead=L-2041");
    await expect(page.getByRole("heading", { level: 2, name: "Азиз Демо" })).toBeVisible();
    await expect(page.getByText("Только просмотр", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /Забрать/ })).toHaveCount(0);
    await expect(page.getByLabel("Сообщение клиенту")).toHaveCount(0);
    await expect(page.getByText("Только просмотр: отвечают менеджеры")).toBeVisible();
    await expectNoViolations(page, "директор");
  });
});

// @mobile: проект mobile (Pixel 7, 390) гоняет только сценарии с этим тегом — экраны с адаптивной логикой.
test(
  "390: список → диалог на весь экран с полем внизу → карточка лида листом с кнопками внизу",
  { tag: "@mobile" },
  async ({ page, isMobile }) => {
    test.skip(!isMobile, "узкий экран — проект mobile");
    await loginAndWait(page, "manager@demo.example");
    await openMessages(page);
    await expect(inbox(page).getByText("ждёт 12 мин")).toBeVisible();
    await settledScreenshot(page, "list");
    await expectNoViolations(page, "очередь 390");

    await inbox(page)
      .getByRole("link", { name: /^Тимур Образцов/ })
      .click();
    await expect(page.getByRole("heading", { level: 2, name: "Тимур Образцов" })).toBeVisible();
    await expect(inbox(page)).toHaveCount(0);
    await expect(page.getByRole("link", { name: /Все диалоги/ })).toBeVisible();
    await expect(composerField(page)).toBeVisible();
    await expect(page.getByText("Уйдёт клиенту в Telegram")).toBeVisible();
    const viewport = page.viewportSize();
    const send = await page.getByRole("button", { name: "Отправить" }).boundingBox();
    expect((send?.x ?? 0) + (send?.width ?? 0)).toBeLessThanOrEqual(viewport?.width ?? 0);
    await settledScreenshot(page, "dialog");
    await expectNoViolations(page, "диалог 390");

    await page.getByRole("button", { name: "Карточка лида" }).click();
    const sheet = page.getByRole("dialog", { name: "Карточка лида" });
    await expect(sheet).toContainText("zakupki@example.org");
    const close = await sheet.getByRole("button", { name: "Закрыть" }).boundingBox();
    const back = await sheet.getByRole("button", { name: "Вернуть боту" }).boundingBox();
    expect(close?.y ?? 0).toBeGreaterThan((viewport?.height ?? 0) * 0.8);
    expect(back?.y ?? 0).toBeGreaterThan((viewport?.height ?? 0) * 0.8);
    await settledScreenshot(page, "lead-sheet");
    await expectNoViolations(page, "карточка 390");
    await sheet.getByRole("button", { name: "Закрыть" }).click();

    // Ошибка отправки на 390: текст в поле, «Повторить» рядом
    await setFlag(page, TELEGRAM_DOWN, true);
    await composerField(page).fill("Счёт пришлю до 17:00");
    await page.getByRole("button", { name: "Отправить" }).click();
    await expect(page.getByText("Не отправлено: Telegram не ответил.")).toBeVisible();
    await expect(composerField(page)).toHaveValue("Счёт пришлю до 17:00");
    await settledScreenshot(page, "send-error");
    await expectNoViolations(page, "ошибка отправки 390");
    await setFlag(page, TELEGRAM_DOWN, false);

    await page.getByRole("link", { name: /Все диалоги/ }).click();
    await expect(inbox(page)).toBeVisible();
  },
);

test("390: пустая очередь", { tag: "@mobile" }, async ({ page, isMobile }) => {
  test.skip(!isMobile, "узкий экран — проект mobile");
  await loginAndWait(page, "manager@demo.example");
  await setFlag(page, INBOX_EMPTY, true);
  await openMessages(page);
  await expect(page.getByRole("heading", { name: "Все передачи разобраны" })).toBeVisible();
  await settledScreenshot(page, "empty");
  await expectNoViolations(page, "пустое состояние 390");
});
