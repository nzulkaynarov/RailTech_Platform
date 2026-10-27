import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import {
  loginAndWait,
  openAvatarMenu,
  settledScreenshot,
  spaGoto,
  waitForMotionEnd,
} from "./support/app";

// Расчёт по заявке на MSW (D2-1, SPEC-v3 §7.4): сценарий ролей целиком — снабженец подтверждает товарные строки,
// гл. инженер — услугу; после второй визы «Расчёт готов» активна и отправляет черновик КП директору; роль без
// себестоимости (гл. инженер) не видит закупку и наценку; axe (WCAG 2.1 AA); на 390 px строки — карточками, «Задание» —
// лист на весь экран (@mobile, B-020).
const NUMBER = "ЗВ-2026-097";
const PANEL = "#pf-context-panel";
const READY = "Расчёт готов → черновик КП директору";
const RAIL = "Перевод стрелочный Р65 марки 1/11";
const DRIVE = "Привод стрелочный электромеханический СП-6М";
const MOUNTING = "Монтаж и пусконаладка стрелочного перевода";

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

async function signOut(page: Page): Promise<void> {
  await openAvatarMenu(page);
  await page.getByRole("menuitem", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login/);
}

async function openCalc(page: Page): Promise<void> {
  await spaGoto(page, `/erp/calc/${encodeURIComponent(NUMBER)}`);
  await expect(
    page.getByRole("heading", { level: 1, name: `Расчёт по заявке ${NUMBER}` }),
  ).toBeVisible();
}

function line(page: Page, name: string) {
  return page.getByRole("row").filter({ has: page.getByText(name, { exact: true }) });
}

test.describe("Расчёт по заявке: снабженец и гл. инженер", () => {
  test.skip(({ isMobile }) => isMobile, "сценарий на десктопе; телефон — блок @mobile");

  test("визы по зонам → «Расчёт готов» → черновик КП директору", async ({ page }) => {
    await loginAndWait(page, "supply@demo.example");

    // Заявки в расчёте: ЗВ · клиент · стадия · срок · три индикатора виз · ответственный · «Открыть расчёт».
    await spaGoto(page, "/erp/requests");
    await expect(page.getByRole("heading", { level: 1, name: "Заявки в расчёте" })).toBeVisible();
    const row = page
      .getByRole("row")
      .filter({ has: page.getByRole("link", { name: `Открыть расчёт по заявке ${NUMBER}` }) });
    await expect(row.getByText("АО «Пример Логистик»")).toBeVisible();
    await expect(row.getByText("Снабжение · ждёт")).toBeVisible();
    await expect(row.getByText("Гл. инженер · ждёт")).toBeVisible();
    await settledScreenshot(page, "requests");
    await expectNoViolations(page, "заявки в расчёте");

    // Клик по строке — «Задание» в боковом окне без перехода.
    await row.getByText("АО «Пример Логистик»").click();
    const panel = page.locator(PANEL);
    await expect(panel.getByText(/Посчитать переводы со склада и под заказ/)).toBeVisible();
    await expect(panel.getByRole("heading", { name: "Визы по заявке" })).toBeVisible();
    await settledScreenshot(page, "requests-task");

    // Расчёт снабженца: закупка и наценка видны, «Расчёт готов» неактивна с подписью почему.
    await panel.getByRole("link", { name: "Открыть расчёт" }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: `Расчёт по заявке ${NUMBER}` }),
    ).toBeVisible();
    await expect(
      page.getByRole("list", { name: `Путь заявки ${NUMBER}` }).locator('[aria-current="step"]'),
    ).toContainText("Расчёт");
    await expect(line(page, RAIL).getByText("Товар под заказ")).toBeVisible();
    await expect(line(page, DRIVE).getByText("На складе · 6")).toBeVisible();
    await expect(page.getByRole("button", { name: READY })).toBeDisabled();
    await expect(
      page.getByText(/без визы 3\. Ждут визы: Склад, Снабжение, Гл\. инженер\./),
    ).toBeVisible();
    await expect(line(page, MOUNTING).getByText("Гл. инженер · ждёт")).toBeVisible();
    await settledScreenshot(page, "calc-supply");
    await expectNoViolations(page, "расчёт снабженца");

    // Правка снимает визу: цена клиенту → наценка пересчитана; затем снабженец подтверждает обе товарные строки.
    const client = line(page, RAIL).getByLabel(`Цена клиенту без НДС за единицу для «${RAIL}»`);
    await client.fill("108000000");
    await client.press("Enter");
    await expect(line(page, RAIL).getByText("20.0")).toBeVisible();
    await line(page, RAIL)
      .getByRole("button", { name: `Подтвердить строку «${RAIL}»` })
      .click();
    await expect(line(page, RAIL).getByText("Снабжение ✓ Демо Снабженцев")).toBeVisible();
    await line(page, DRIVE)
      .getByRole("button", { name: `Подтвердить строку «${DRIVE}»` })
      .click();
    await expect(line(page, DRIVE).getByText("Склад ✓ Демо Снабженцев")).toBeVisible();
    await expect(page.getByText(/без визы 1\. Ждут визы: Гл\. инженер\./)).toBeVisible();
    await expect(page.getByRole("button", { name: READY })).toBeDisabled();
    await expect(
      line(page, MOUNTING).getByRole("button", { name: /Подтвердить строку/ }),
    ).toHaveCount(0);
    await settledScreenshot(page, "calc-supply-signed");

    // Гл. инженер: без доступа к себестоимости закупка товаров и наценка скрыты; правит ставку и дни, подтверждает услугу.
    await signOut(page);
    await loginAndWait(page, "engineer@demo.example");
    await openCalc(page);
    await expect(line(page, RAIL).getByLabel(/Закупка за единицу/)).toHaveCount(0);
    await expect(page.getByText("90 000 000")).toHaveCount(0);
    await expect(line(page, RAIL).getByText("20.0")).toHaveCount(0);
    const days = line(page, MOUNTING).getByLabel(`Дней работы бригады для «${MOUNTING}»`);
    await days.fill("4");
    await days.press("Enter");
    await expect(days).toHaveValue(/^4(\.0)?$/);
    await line(page, MOUNTING)
      .getByRole("button", { name: `Подтвердить строку «${MOUNTING}»` })
      .click();
    await expect(line(page, MOUNTING).getByText("Гл. инженер ✓ Демо Инженеров")).toBeVisible();
    const ready = page.getByRole("button", { name: READY });
    await expect(ready).toBeEnabled();
    await settledScreenshot(page, "calc-engineer-ready");
    await expectNoViolations(page, "расчёт гл. инженера, все визы");

    // «Расчёт готов» — КП уходит директору, строки закрываются для правки.
    await ready.click();
    await expect(page.getByText(/Черновик КП КП-2026\/115 у директора на одобрении/)).toBeVisible();
    await expect(page.getByRole("button", { name: READY })).toHaveCount(0);
    await expect(
      line(page, MOUNTING).getByLabel(`Ставка бригады для «${MOUNTING}»`),
    ).toBeDisabled();
    await settledScreenshot(page, "calc-at-director");
    await expectNoViolations(page, "расчёт у директора");
  });

  test("бухгалтер: только чтение, итог закупки виден, кнопок визы нет", async ({ page }) => {
    await loginAndWait(page, "accountant@demo.example");
    await openCalc(page);
    await expect(page.getByText(/Только чтение: строки правит и визирует снабженец/)).toBeVisible();
    await expect(page.getByRole("button", { name: /Подтвердить строку/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: READY })).toHaveCount(0);
    await settledScreenshot(page, "calc-accountant");
    await expectNoViolations(page, "расчёт бухгалтера");
  });

  test("ИИ-разбор: предложение без записи, строки добавляет человек", async ({ page }) => {
    await loginAndWait(page, "engineer@demo.example");
    await spaGoto(page, `/erp/calc/${encodeURIComponent("ЗВ-2026-103")}`);
    await expect(page.getByRole("heading", { name: "Расчёт ещё не начат" })).toBeVisible();
    await settledScreenshot(page, "calc-not-started");
    await page.getByRole("button", { name: "Начать расчёт" }).click();
    await expect(
      page.getByText("Строк пока нет. Добавьте строку или разберите текст заявки."),
    ).toBeVisible();
    await page.getByRole("button", { name: "Разобрать текст заявки" }).click();
    const dialog = page.getByRole("dialog", { name: "ИИ-разбор текста заявки" });
    await dialog.getByRole("button", { name: "Разобрать" }).click();
    await expect(dialog.getByText("Обследование стрелочного перевода · 6 шт.")).toBeVisible();
    await expect(page.getByRole("row")).toHaveCount(0);
    await settledScreenshot(page, "calc-parse");
    await expectNoViolations(page, "ИИ-разбор");
    // Гл. инженер добавляет только услугу: товарные строки снять, тип первой — «Услуга».
    await dialog.getByRole("checkbox", { name: /Крестовина/ }).uncheck();
    await dialog.getByRole("checkbox", { name: /Остряк/ }).uncheck();
    await dialog.getByRole("button", { name: "Добавить выбранные (1)" }).click();
    await expect(dialog).toBeHidden();
    await expect(line(page, "Обследование стрелочного перевода").getByText("Услуга")).toBeVisible();
  });
});

test.describe("Расчёт на телефоне @mobile", () => {
  test.skip(({ isMobile }) => !isMobile, "только проект mobile (390 px)");

  test("@mobile заявки и строки карточками; «Задание» — лист на весь экран", async ({ page }) => {
    await loginAndWait(page, "engineer@demo.example");
    await spaGoto(page, "/erp/requests");
    await expect(page.getByRole("heading", { level: 1, name: "Заявки в расчёте" })).toBeVisible();
    await expect(page.getByRole("list", { name: "Заявки в расчёте" })).toBeVisible();
    await settledScreenshot(page, "requests");
    await expectNoViolations(page, "заявки на телефоне");

    await openCalc(page);
    await expect(
      page.getByRole("list", { name: `Строки расчёта по заявке ${NUMBER}` }),
    ).toBeVisible();
    await settledScreenshot(page, "calc");
    await expectNoViolations(page, "расчёт на телефоне");

    await page.getByRole("button", { name: "Задание и визы" }).click();
    const sheet = page.getByRole("dialog", { name: "Задание" });
    await expect(sheet.getByText(/Посчитать переводы со склада и под заказ/)).toBeVisible();
    await expect(sheet.getByRole("button", { name: "Закрыть" })).toBeVisible();
    await settledScreenshot(page, "calc-task");
    await expectNoViolations(page, "задание листом");
    await sheet.getByRole("button", { name: "Закрыть" }).click();
    await expect(sheet).toBeHidden();
  });
});
