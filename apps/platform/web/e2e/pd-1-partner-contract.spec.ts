import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ПД-1: договор кандидата в партнёры без тупика на MSW — подготовка из шаблона библиотеки или своим файлом,
// согласование держателем зоны «Право», что мешает отправить — словами. Снимки 1512, 1440 и 390 px и axe (WCAG 2.1 AA).

const WIDTHS = [1512, 1440, 390] as const;
const LIST = "Очередь заявок кандидатов в партнёры";

async function openQueue(page: import("@playwright/test").Page, width: number) {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
  await loginAndWait(page, "supply@demo.example");
  await spaGoto(page, "/crm/clients?kind=applications");
  const list = page.getByRole(width === 390 ? "list" : "table", { name: LIST });
  await expect(list.getByText("Nanjing Jichuang Co.")).toBeVisible();
  return list;
}

for (const width of WIDTHS) {
  test(`договор из шаблона: подготовка и согласование, ${String(width)} px`, async ({ page }) => {
    const list = await openQueue(page, width);

    // Договора нет: сказано, чего не хватает, и дана ссылка на библиотеку шаблонов; отправлять нечего
    await expect(list.getByText("Договор не подготовлен.")).toBeVisible();
    await expect(list.getByRole("link", { name: "Шаблоны договоров" })).toBeVisible();
    await expectNoViolations(page, "заявки партнёров · договор не подготовлен");
    await settledScreenshot(page, "pd1-queue");

    // Подготовка из утверждённого шаблона по умолчанию; отступление уходит на решение «Право»
    const nanjing = list
      .getByText("Nanjing Jichuang Co.")
      .locator("xpath=ancestor::*[self::tr or self::li][1]");
    await nanjing.getByRole("button", { name: "Подготовить договор" }).click();
    const prepare = page.getByRole("dialog", {
      name: /Договор для кандидата: Nanjing Jichuang Co\./,
    });
    await expect(prepare.getByText("Договор с партнёром · ред. 2")).toBeVisible();
    await expect(prepare.getByText("Согласование не нужно", { exact: false })).toBeVisible();
    await expectNoViolations(page, "заявки партнёров · подготовка договора");
    await settledScreenshot(page, "pd1-prepare");
    await prepare.getByLabel("Чем отличается от шаблона").fill("Срок оплаты 45 дней");
    await expect(prepare.getByText("Решит: Анвар Юристов", { exact: false })).toBeVisible();
    await prepare.getByRole("button", { name: "Подготовить договор" }).click();
    await expect(prepare).toBeHidden();
    await expect(list.getByText("Ждёт решения: Анвар Юристов").first()).toBeVisible();
    await settledScreenshot(page, "pd1-waiting");
  });

  test(`решение «Право» по своему файлу, ${String(width)} px`, async ({ page }) => {
    await page.addInitScript(`window.localStorage.setItem("rt-pf-mock-legal-holder", "1");`);
    const list = await openQueue(page, width);

    await list.getByRole("button", { name: "Решить по договору" }).click();
    const decision = page.getByRole("dialog", {
      name: /Решение по договору: Zhengzhou Rail Parts/,
    });
    await expect(decision.getByText("Сотрудник загрузил свой файл договора.")).toBeVisible();
    await expectNoViolations(page, "заявки партнёров · решение по договору");
    await settledScreenshot(page, "pd1-decision");
    await decision.getByText("Вернуть", { exact: true }).click();
    const ok = decision.getByRole("button", { name: "Вернуть на доработку" });
    await expect(ok).toBeDisabled();
    await decision.getByLabel("Замечание").fill("Нет пункта об ответственности");
    await ok.click();
    await expect(decision).toBeHidden();
    await expect(list.getByText("Возвращён: Нет пункта об ответственности")).toBeVisible();
  });

  test(`нет утверждённого шаблона, ${String(width)} px`, async ({ page }) => {
    await page.addInitScript(`window.localStorage.setItem("rt-pf-mock-no-partner-template", "1");`);
    const list = await openQueue(page, width);

    const nanjing = list
      .getByText("Nanjing Jichuang Co.")
      .locator("xpath=ancestor::*[self::tr or self::li][1]");
    await nanjing.getByRole("button", { name: "Подготовить договор" }).click();
    const prepare = page.getByRole("dialog", { name: /Договор для кандидата/ });
    await expect(
      prepare.getByText("Нет утверждённого шаблона партнёрского договора", { exact: false }),
    ).toBeVisible();
    await expect(prepare.getByRole("link", { name: "Открыть шаблоны договоров" })).toBeVisible();
    await expect(prepare.getByRole("button", { name: "Подготовить договор" })).toBeDisabled();
    await expectNoViolations(page, "заявки партнёров · нет шаблона");
    await settledScreenshot(page, "pd1-no-template");
  });
}
