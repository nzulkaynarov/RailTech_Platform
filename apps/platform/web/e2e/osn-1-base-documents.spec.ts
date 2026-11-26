import { expect, test, type Page } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ОСН-1: базовые документы компании и пакет для партнёра на MSW — пометка «Базовый документ» в списке шаблонов договоров,
// пакет в «Подготовить договор», роль без утверждённого шаблона названа фразой со ссылкой. Снимки 1512, 1440 и 390 px и axe.

const WIDTHS = [1512, 1440, 390] as const;
const QUEUE = "Очередь заявок кандидатов в партнёры";

async function size(page: Page, width: number) {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
}

for (const width of WIDTHS) {
  test(`шаблоны договоров: пометка базового документа, ${String(width)} px`, async ({ page }) => {
    await size(page, width);
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/templates?tab=contracts");
    const table = page.getByRole("table", { name: "Шаблоны договоров" });
    await expect(table.getByText("Базовый документ: Договор о партнёрстве")).toBeVisible();
    await expectNoViolations(page, "шаблоны договоров · пометка базового документа");
    await settledScreenshot(page, "osn1-templates");

    const draft = table
      .getByText("Договор с партнёром · услуги")
      .locator("xpath=ancestor::*[self::tr or self::li][1]");
    await draft.getByRole("button", { name: /Действия/ }).click();
    await page.getByRole("menuitem", { name: "Базовый документ" }).click();
    const dialog = page.getByRole("dialog", {
      name: /Базовый документ: Договор с партнёром · услуги/,
    });
    await expect(
      dialog.getByText("Базовый документ утверждается один раз", { exact: false }),
    ).toBeVisible();
    await expectNoViolations(page, "шаблоны договоров · окно пометки");
    await settledScreenshot(page, "osn1-mark");
  });

  test(`пакет для кандидата в партнёры, ${String(width)} px`, async ({ page }) => {
    await page.addInitScript(`window.localStorage.setItem("rt-pf-mock-package", "ready");`);
    await size(page, width);
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/crm/clients?kind=applications");
    const list = page.getByRole(width === 390 ? "list" : "table", { name: QUEUE });
    const nanjing = list
      .getByText("Nanjing Jichuang Co.")
      .locator("xpath=ancestor::*[self::tr or self::li][1]");
    await nanjing.getByRole("button", { name: "Подготовить договор" }).click();
    const prepare = page.getByRole("dialog", {
      name: /Договор для кандидата: Nanjing Jichuang Co\./,
    });
    await expect(prepare.getByText("Соглашение о неразглашении · ред. 1")).toBeVisible();
    await expect(prepare.getByText("пакет готов к отправке", { exact: false })).toBeVisible();
    await expectNoViolations(page, "заявки партнёров · пакет документов");
    await settledScreenshot(page, "osn1-package-prepare");
    await prepare.getByRole("button", { name: "Подготовить договор" }).click();
    await expect(prepare).toBeHidden();
    await expect(
      list.getByText("Пакет: Договор о партнёрстве, Соглашение о неразглашении").first(),
    ).toBeVisible();
    await expectNoViolations(page, "заявки партнёров · пакет подготовлен");
    await settledScreenshot(page, "osn1-package-card");
  });

  test(`нет утверждённого шаблона роли, ${String(width)} px`, async ({ page }) => {
    await page.addInitScript(`window.localStorage.setItem("rt-pf-mock-package", "missing");`);
    await size(page, width);
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/crm/clients?kind=applications");
    const list = page.getByRole(width === 390 ? "list" : "table", { name: QUEUE });
    const nanjing = list
      .getByText("Nanjing Jichuang Co.")
      .locator("xpath=ancestor::*[self::tr or self::li][1]");
    await nanjing.getByRole("button", { name: "Подготовить договор" }).click();
    const prepare = page.getByRole("dialog", { name: /Договор для кандидата/ });
    await expect(
      prepare.getByText("Нет утверждённого шаблона: Соглашение о неразглашении."),
    ).toBeVisible();
    await expect(prepare.getByRole("link", { name: "Шаблоны договоров" })).toBeVisible();
    await expect(prepare.getByRole("button", { name: "Подготовить договор" })).toBeDisabled();
    await expectNoViolations(page, "заявки партнёров · нет шаблона роли");
    await settledScreenshot(page, "osn1-package-missing");
  });

  test(`уже подписано на бумаге, ${String(width)} px`, async ({ page }) => {
    await page.addInitScript(`window.localStorage.setItem("rt-pf-mock-package", "ready");`);
    await size(page, width);
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/crm/clients?kind=applications");
    const list = page.getByRole(width === 390 ? "list" : "table", { name: QUEUE });
    const nanjing = list
      .getByText("Nanjing Jichuang Co.")
      .locator("xpath=ancestor::*[self::tr or self::li][1]");
    await nanjing.getByRole("button", { name: "Ещё" }).click();
    await page.getByRole("menuitem", { name: "Уже подписано на бумаге" }).click();
    const dialog = page.getByRole("dialog", { name: /Уже подписано на бумаге: Nanjing/ });
    await expect(
      dialog.getByText("в Кабинет и по почте ничего не уйдёт", { exact: false }),
    ).toBeVisible();
    const date = dialog.getByLabel("Когда подписано");
    await date.fill("14.03.2025");
    await date.press("Enter");
    await expectNoViolations(page, "заявки партнёров · уже подписано на бумаге");
    await settledScreenshot(page, "osn1-archive");
    await dialog.getByRole("button", { name: "Внести" }).click();
    await expect(dialog).toBeHidden();
    await expect(list.getByText("Внесено из архива").first()).toBeVisible();
    await expectNoViolations(page, "заявки партнёров · внесено из архива");
    await settledScreenshot(page, "osn1-archive-done");
  });
}
