import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import {
  loginAndWait,
  openAvatarMenu,
  settledScreenshot,
  spaGoto,
  waitForMotionEnd,
} from "./support/app";

// EDS-REG PR 2 на MSW: шаблоны резолюций (R2). Администратор заводит общий шаблон в Настройки · Документооборот, директор
// заполняет резолюцию «Из шаблона», правит и сохраняет свою как шаблон. axe 0 и снимки 1440 и 390
// (`E2E_SCREENSHOT_DIR` → docs/screens/eds-reg-2/).
const WIDTHS = [1440, 390] as const;
const TAX = "/eds/inbox/%D0%92%D0%A5-108%2F26?panel=open&tab=resolution";

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

async function shoot(page: Page, name: string, prepare?: () => Promise<void>): Promise<void> {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    if (prepare) await prepare();
    await expectNoViolations(page, `${name} ${String(width)}`);
    await settledScreenshot(page, name);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

async function signOut(page: Page): Promise<void> {
  await openAvatarMenu(page);
  await page.getByRole("menuitem", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login/);
}

async function pickTemplate(page: Page, name: string): Promise<void> {
  const form = page.getByRole("form", { name: "Резолюция директора" });
  await form.getByLabel("Из шаблона").click();
  await page
    .locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden)")
    .getByText(name, { exact: true })
    .click();
}

test.describe("EDS-REG · шаблоны резолюций", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("общий шаблон администратора и «Из шаблона» у директора", async ({ page }) => {
    // 1. Администратор: Настройки → Процессы · Шаблоны резолюций (старый адрес «Документооборота» уводит туда), новый шаблон.
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/docflow?tab=templates");
    await expect(page.getByRole("heading", { level: 1, name: "Шаблоны резолюций" })).toBeVisible();
    // Список загружен (общий шаблон мока виден) — кнопка «Добавить шаблон» одна.
    await expect(page.getByText("Банк — к сведению бухгалтерии", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Добавить шаблон" }).click();
    const dialog = page.getByRole("dialog", { name: "Новый шаблон резолюции" });
    await dialog.getByLabel("Название шаблона").fill("Госорган — к исполнению");
    await dialog.getByLabel("Текст резолюции").fill("Исполнить в срок и доложить.");
    await dialog.getByLabel("Срок, дней").fill("10");
    await shoot(page, "templates-add");
    await dialog.getByRole("button", { name: "Сохранить" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText("Госорган — к исполнению", { exact: true })).toBeVisible();
    await expect(page.locator(".ant-message-notice")).toHaveCount(0, { timeout: 10_000 });
    await shoot(page, "templates-list");
    await signOut(page);

    // 2. Директор: письмо ВХ-108/26, «Из шаблона» — личный шаблон, поля заполнены (на 390 форма — нижний лист,
    // поэтому сценарий проходится на каждой ширине заново).
    await loginAndWait(page, "director@demo.example");
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await spaGoto(page, width === 390 ? TAX.replace("panel=open", "sheet=resolution") : TAX);
      const form = page.getByRole("form", { name: "Резолюция директора" });
      await expect(form.getByLabel("Из шаблона")).toBeVisible();
      await pickTemplate(page, "Налоговая — ответ бухгалтерии");
      await expect(form.getByRole("radio", { name: /Подготовить ответ/ })).toBeChecked();
      await expect(form.getByLabel("Текст резолюции")).toHaveValue(
        "Подготовить ответ в срок, проект — мне на согласование.",
      );
      await expect(page.locator(".ant-message-notice")).toHaveCount(0, { timeout: 10_000 });
      await expectNoViolations(page, `resolution-from-template ${String(width)}`);
      await settledScreenshot(page, "resolution-from-template");

      // 3. Общий шаблон администратора тоже в списке; «Сохранить как шаблон».
      await pickTemplate(page, "Госорган — к исполнению");
      await expect(form.getByRole("radio", { name: /К исполнению/ })).toBeChecked();
      await form.getByRole("button", { name: "Сохранить как шаблон" }).click();
      const save = page.getByRole("dialog", { name: "Сохранить как шаблон" });
      await save.getByLabel("Название шаблона").fill(`Госорган — мой вариант ${String(width)}`);
      await expectNoViolations(page, `resolution-save-template ${String(width)}`);
      await settledScreenshot(page, "resolution-save-template");
      await save.getByRole("button", { name: "Сохранить" }).click();
      await expect(
        page.getByText(`Шаблон «Госорган — мой вариант ${String(width)}» сохранён.`),
      ).toBeVisible();
    }
  });
});
