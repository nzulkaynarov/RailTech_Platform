import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";
import { chooseOption, fillDate, pickFiles } from "./support/fields";

// SIGN-2 на MSW: «Настройки · Права подписи» (ADR-0024 п. 1–2, 8). Администратор видит действующие полномочия с «истекает через
// N дней», выдаёт приказ, прикладывает скан, отзывает с причиной (блок «Что произойдёт») и проверяет, кто вправе подписать.
// axe 0 и снимки 1440 и 390 (`E2E_SCREENSHOT_DIR` → docs/screens/SIGN-2/).
const WIDTHS = [1440, 390] as const;

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

async function shoot(page: Page, name: string): Promise<void> {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await expectNoViolations(page, `${name} ${String(width)}`);
    await settledScreenshot(page, name);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

test.describe("SIGN-2 · Права подписи", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("реестр: список, выдача приказа со сканом, отзыв с причиной, проверка «кто подпишет»", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/signing");
    await expect(page.getByRole("heading", { level: 1, name: "Права подписи" })).toBeVisible();
    const manager = page.getByRole("row", { name: /Демо Менеджеров/ });
    await expect(manager).toContainText("истекает через 14 дней");
    await expect(manager).toContainText("Скоро истекает");
    await expect(page.getByRole("row", { name: /Демо Директоров/ })).toContainText("Устав");
    await expect(page.locator(".ant-message-notice")).toHaveCount(0, { timeout: 10_000 });
    await shoot(page, "signing-list");

    // «Все» — истёкшее и отозванное словами
    await page.getByText("Все", { exact: true }).click();
    await expect(page.getByRole("row", { name: /Демо Инженеров/ })).toContainText("Отозвано");
    await expect(page.getByRole("row", { name: /Демо Снабженцев/ })).toContainText("Срок вышел");
    await shoot(page, "signing-list-all");
    await page.getByText("Действующие", { exact: true }).click();

    // Карточка доверенности с журналом и файлом основания
    await page.getByRole("button", { name: "Открыть полномочие: Демо Менеджеров" }).click();
    const card = page.getByRole("dialog", { name: "Полномочие: Демо Менеджеров" });
    await expect(card.getByText("Журнал", { exact: true })).toBeVisible();
    await expect(card.getByRole("link", { name: /doverennost-17\.pdf/ })).toBeVisible();
    await shoot(page, "signing-card");
    await card.getByRole("button", { name: "Закрыть" }).click();
    await expect(card).toBeHidden();

    // Выдать приказ и приложить скан
    await page.getByRole("button", { name: "Выдать полномочие" }).first().click();
    const drawer = page.getByRole("dialog", { name: "Выдать полномочие подписи" });
    await chooseOption(
      drawer.getByRole("combobox", { name: "Сотрудник" }),
      "Демо Снабженцев · Специалист по снабжению",
    );
    await chooseOption(drawer.getByRole("combobox", { name: "Что подписывает" }), "Счёт");
    await drawer.getByRole("radio", { name: "Приказ" }).check();
    await drawer.getByLabel("Номер").fill("21-к");
    await fillDate(drawer.getByLabel("Дата выдачи"), "2026-10-01");
    await pickFiles(drawer.getByLabel("Файл основания"), {
      name: "prikaz-21.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4 demo"),
    });
    await shoot(page, "signing-add");
    await drawer.getByRole("button", { name: "Сохранить" }).click();
    await expect(drawer).toBeHidden();
    await expect(page.getByRole("row", { name: /Демо Снабженцев/ })).toContainText(
      "Приказ № 21-к от 01.10.2026",
    );
    await expect(page.locator(".ant-message-notice")).toHaveCount(0, { timeout: 10_000 });

    // Отзыв: причина обязательна, «Что произойдёт»
    await page.getByRole("button", { name: "Открыть полномочие: Демо Менеджеров" }).click();
    await page
      .getByRole("dialog", { name: "Полномочие: Демо Менеджеров" })
      .getByRole("button", { name: "Отозвать" })
      .click();
    const modal = page.getByRole("dialog", { name: "Отозвать полномочие: Демо Менеджеров" });
    await expect(modal.getByText("Что произойдёт")).toBeVisible();
    await modal.getByLabel("Причина").fill("Доверенность отозвана приказом");
    await shoot(page, "signing-revoke");
    await modal.getByRole("button", { name: "Отозвать" }).click();
    await expect(modal).toBeHidden();
    await expect(page.getByRole("row", { name: /Демо Менеджеров/ })).toHaveCount(0);
    await expect(page.locator(".ant-message-notice")).toHaveCount(0, { timeout: 10_000 });

    // Проверка правил
    const check = page.locator(".pf-sign-check");
    await chooseOption(check.getByRole("combobox", { name: "Вид документа" }), "Исходящее письмо");
    await check.getByRole("spinbutton", { name: "Сумма" }).fill("1000");
    await check.getByRole("button", { name: "Проверить" }).click();
    await expect(check.getByRole("heading", { name: "Подпишет" })).toBeVisible();
    await shoot(page, "signing-check");
  });

  test("пустой реестр: подсказка предлагает директора по бланку", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    await page.evaluate('window.localStorage.setItem("rt-pf-mock-signing", "[]")');
    await spaGoto(page, "/admin/signing");
    await expect(page.getByText("Пока никто не вправе подписывать документы")).toBeVisible();
    await expect(page.getByText("Полномочий нет", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Добавить: Демо Директоров" })).toBeVisible();
    await expect(page.locator(".ant-message-notice")).toHaveCount(0, { timeout: 10_000 });
    await shoot(page, "signing-empty");
  });

  test("директор без права не открывает страницу", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/admin/signing");
    await expect(page.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
  });
});
