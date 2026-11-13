import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, openAvatarMenu, settledScreenshot, waitForMotionEnd } from "./support/app";

// EDS-REG PR 1 на MSW: Настройки · Процессы · Справочники (до SET-IA — «Документооборот») — администратор добавляет способ получения и скрывает
// другой; делопроизводитель видит изменения в форме «Зарегистрировать входящее»; журнал отбирает письма по виду документа.
// axe 0 и снимки 1440 и 390 (`E2E_SCREENSHOT_DIR` → docs/screens/eds-reg-1/).
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

async function noHorizontalScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate<number>(
    "document.documentElement.scrollWidth - document.documentElement.clientWidth",
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

async function shoot(page: Page, name: string, prepare?: () => Promise<void>): Promise<void> {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    if (prepare) await prepare();
    await expectNoViolations(page, `${name} ${String(width)}`);
    if (width === 390) await noHorizontalScroll(page);
    await settledScreenshot(page, name);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

async function signOut(page: Page): Promise<void> {
  await openAvatarMenu(page);
  await page.getByRole("menuitem", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login/);
}

test.describe("EDS-REG · справочники документооборота", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("администратор ведёт справочники, делопроизводитель видит их в форме и журнале", async ({
    page,
  }) => {
    // 1. Администратор: Настройки → Процессы · Справочники (SET-IA), виды входящих документов с полями «Срочный» и «Срок».
    await loginAndWait(page, "admin@demo.example");
    await page
      .getByRole("navigation", { name: "Модули" })
      .getByRole("link", { name: "Настройки" })
      .click();
    await page
      .getByRole("navigation", { name: "Разделы модуля" })
      .getByRole("link", { name: "Компания" })
      .click();
    await page.getByRole("link", { name: /Справочники/ }).click();
    await expect(page).toHaveURL(/\/admin\/dictionaries/);
    await expect(page.getByRole("heading", { level: 1, name: "Справочники" })).toBeVisible();
    await page.getByRole("link", { name: "Виды входящих документов" }).click();
    await expect(page.getByText("Требование или уведомление ГНК", { exact: true })).toBeVisible();
    await shoot(page, "dictionaries-kinds");

    // 2. Способы получения: добавить «Фельдъегерская связь», скрыть «Курьер».
    await page.getByText("Способы получения", { exact: true }).click();
    await expect(
      page.getByText("Кабинет налогоплательщика my.soliq", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Добавить значение" }).click();
    const dialog = page.getByRole("region", { name: "Новое значение" });
    await dialog.getByLabel("Название по-русски").fill("Фельдъегерская связь");
    await dialog.getByLabel("Название по-английски").fill("Courier service");
    await shoot(page, "dictionaries-add");
    await dialog.getByRole("button", { name: "Сохранить" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText("Фельдъегерская связь", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Скрыть: Курьер" }).click();
    await expect(page.getByRole("button", { name: "Вернуть: Курьер" })).toBeVisible();
    await expect(page.locator(".ant-message-notice")).toHaveCount(0, { timeout: 10_000 });
    await shoot(page, "dictionaries-methods");
    await signOut(page);

    // 3. Делопроизводитель: в форме — новый способ, скрытого нет.
    await loginAndWait(page, "registrar@demo.example");
    await page.goto("/eds/register");
    await expect(
      page.getByRole("heading", { level: 1, name: "Регистрация входящего документа" }),
    ).toBeVisible();
    await page.getByLabel("Способ получения").click();
    const options = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
    await expect(options.getByText("Фельдъегерская связь", { exact: true })).toBeVisible();
    await expect(options.getByText("Курьер", { exact: true })).toHaveCount(0);
    await settledScreenshot(page, "register-methods");
    await page.keyboard.press("Escape");

    // 4. Журнал: отбор по виду документа.
    await page.goto("/eds/inbox?status=all");
    await page.getByLabel("Вид документа").click();
    await page
      .locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden)")
      .getByText("Письмо банка", { exact: true })
      .click();
    await expect(page).toHaveURL(/kind=bank/);
    await shoot(page, "inbox-kind-filter");
  });
});
