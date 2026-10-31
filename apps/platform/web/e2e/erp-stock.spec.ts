import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import {
  loginAndWait,
  openAvatarMenu,
  settledScreenshot,
  spaGoto,
  waitForMotionEnd,
} from "./support/app";
import { fillDate } from "./support/fields";

// Склад и закупки на MSW (D2-2, SPEC-v3 §7.4): сценарий снабженца целиком — резерв строки из расчёта и «Запросить цену у
// поставщика» (письмо в журнале) → заказ поставщику ЗП: черновик → отправлен (письмо) → подтверждён → приёмка частичная и
// полная (остаток растёт) → отгрузка по проекту уменьшает резерв; просроченный заказ — в «Моих задачах»; роль без раздела
// «Склад» доступа не имеет; axe (WCAG 2.1 AA); на 390 px — карточки вместо таблиц (@mobile).
const YEAR = String(new Date().getFullYear());
const OVERDUE = `ЗП-${YEAR}-029`;
const NEW_ORDER = `ЗП-${YEAR}-030`;
const NUMBER = "ЗВ-2026-097";
const RAIL = "Перевод стрелочный Р65 марки 1/11";
const DRIVE = "Привод стрелочный электромеханический СП-6М";

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

function line(page: Page, name: string) {
  return page.getByRole("row").filter({ has: page.getByText(name, { exact: true }) });
}

function stockRow(page: Page, name: string) {
  return page
    .getByRole("table", { name: "Остатки и резервы по номенклатуре" })
    .getByRole("row")
    .filter({ has: page.getByRole("button", { name: `Открыть товар «${name}»` }) });
}

test.describe("Склад и закупки: снабженец", () => {
  test.skip(({ isMobile }) => isMobile, "сценарий на десктопе; телефон — блок @mobile");

  test("резерв из расчёта и запрос цены → заказ ЗП → приёмка → отгрузка по проекту", async ({
    page,
  }) => {
    await loginAndWait(page, "supply@demo.example");

    // Расчёт: колонка «Склад» — ячейка, свободное, резерв; «Зарезервировать» и «Запросить цену у поставщика».
    await spaGoto(page, `/erp/calc/${encodeURIComponent(NUMBER)}`);
    await expect(
      page.getByRole("heading", { level: 1, name: `Расчёт по заявке ${NUMBER}` }),
    ).toBeVisible();
    await expect(line(page, DRIVE).getByText("Ячейка B-04-1")).toBeVisible();
    await expect(line(page, DRIVE).getByText("Свободно · 6")).toBeVisible();
    await line(page, DRIVE)
      .getByRole("button", { name: `Зарезервировать 4 для «${DRIVE}»` })
      .click();
    await expect(line(page, DRIVE).getByText("Резерв · 4")).toBeVisible();
    await expect(line(page, DRIVE).getByText("Свободно · 2")).toBeVisible();
    await line(page, RAIL)
      .getByRole("button", { name: `Зарезервировать 1 для «${RAIL}»` })
      .click();
    await expect(line(page, RAIL).getByText("Резерв · 1")).toBeVisible();

    await page.getByRole("button", { name: "Запросить цену у поставщика" }).click();
    const request = page.getByRole("dialog", { name: `Запросить цену у поставщика · ${NUMBER}` });
    await request.getByRole("combobox", { name: "Поставщик" }).click();
    await page.getByTitle(/ООО «Вымышленная Сталь» · sales@steel\.example/).click();
    await settledScreenshot(page, "calc-price-request");
    await request.getByRole("button", { name: "Отправить запрос" }).click();
    await expect(page.getByText("Запрос ушёл на sales@steel.example")).toBeVisible();
    const journal = page.getByRole("list", { name: "Запросы цены у поставщиков" });
    await expect(journal.getByText("Ждём ответ")).toBeVisible();
    await expect(journal.getByText(/Демо Снабженцев → sales@steel\.example/)).toBeVisible();
    await settledScreenshot(page, "calc-stock");
    await journal.scrollIntoViewIfNeeded();
    await settledScreenshot(page, "calc-price-journal");
    await expectNoViolations(page, "расчёт: склад и запрос цены");

    // Склад · остатки и резервы.
    await spaGoto(page, "/erp/stock");
    await expect(page.getByRole("heading", { level: 1, name: "Склад" })).toBeVisible();
    await expect(stockRow(page, DRIVE).getByText("Свободно · 2")).toBeVisible();
    await expect(stockRow(page, "Скрепление рельсовое КБ-65").getByText("+30")).toBeVisible();
    await settledScreenshot(page, "stock-balances");
    await expectNoViolations(page, "остатки и резервы");

    // Заказы поставщикам: просроченный ЗП виден, новый — черновик → отправлен → подтверждён.
    await page.getByRole("tab", { name: "Заказы поставщикам" }).click();
    const overdueRow = page.getByRole("row").filter({ hasText: OVERDUE });
    await expect(overdueRow.getByText("Просрочен · 3 дн.")).toBeVisible();
    await settledScreenshot(page, "stock-orders");
    await expectNoViolations(page, "заказы поставщикам");
    await page.getByRole("button", { name: "Создать заказ" }).click();
    const create = page.getByRole("dialog", { name: "Новый заказ поставщику" });
    await create.getByRole("combobox", { name: "Поставщик" }).click();
    // Вариант списка поставщиков (у ячейки таблицы тоже есть `title` с полным именем — UX-1c)
    await page.locator(".ant-select-dropdown").getByTitle("ООО «Вымышленная Сталь»").click();
    const product = create.getByRole("combobox", { name: "Товар, строка 1" });
    await product.click();
    await product.pressSequentially("перевод");
    await page.getByTitle(/Перевод стрелочный Р65 марки 1\/11/).click();
    await create.getByRole("spinbutton", { name: "Количество, строка 1" }).fill("4");
    await create.getByRole("button", { name: "Создать черновик" }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: `Заказ поставщику ${NEW_ORDER}` }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Принять товар" })).toHaveCount(0);
    await settledScreenshot(page, "order-draft");
    await page.getByRole("button", { name: "Отправить поставщику" }).click();
    const send = page.getByRole("dialog", { name: `Отправить заказ ${NEW_ORDER} поставщику` });
    await expect(send.getByText("Что произойдёт")).toBeVisible();
    await send.getByRole("button", { name: "Отправить письмо" }).click();
    await expect(page.getByText("Заказ отправлен поставщику")).toBeVisible();
    await expect(
      page.getByRole("list", { name: "Журнал заказа" }).getByText("Отправлен поставщику"),
    ).toBeVisible();
    await page.getByRole("button", { name: "Поставщик подтвердил" }).click();
    const confirm = page.getByRole("dialog", { name: `Поставщик подтвердил заказ ${NEW_ORDER}` });
    await fillDate(confirm.getByLabel("Подтверждённая дата поставки"), "2099-01-15");
    await confirm.getByRole("button", { name: "Подтвердить" }).click();
    await expect(page.getByRole("button", { name: "Принять товар" })).toBeVisible();
    await settledScreenshot(page, "order-confirmed");
    await expectNoViolations(page, "карточка заказа");

    // Приёмка частичная, затем полная: остаток склада растёт.
    await page.getByRole("button", { name: "Принять товар" }).click();
    const receive = page.getByRole("dialog", { name: `Принять товар по заказу ${NEW_ORDER}` });
    await receive.getByRole("spinbutton", { name: /Принять/ }).fill("3");
    await receive.getByRole("textbox", { name: /Ячейка для/ }).fill("A-03-2");
    await receive.getByRole("button", { name: "Принять" }).click();
    await expect(page.getByText("Товар принят")).toBeVisible();
    await expect(
      page.getByRole("list", { name: "Журнал заказа" }).getByText("Принят товар"),
    ).toBeVisible();
    await page.getByRole("button", { name: "Принять товар" }).click();
    await receive.getByRole("textbox", { name: /Ячейка для/ }).fill("A-03-2");
    await receive.getByRole("button", { name: "Принять" }).click();
    await expect(page.getByRole("button", { name: "Принять товар" })).toHaveCount(0);
    await expect(
      page.getByRole("list", { name: "Журнал заказа" }).getByText("Заказ получен целиком"),
    ).toBeVisible();
    await spaGoto(page, "/erp/stock");
    await expect(stockRow(page, RAIL).getByText("A-03-2: 5")).toBeVisible();
    await expect(stockRow(page, RAIL).getByText("Свободно · 4")).toBeVisible();

    // Приёмка: ждут товара строки подтверждённого просроченного заказа.
    await page.getByRole("tab", { name: "Приёмка" }).click();
    await expect(
      page.getByRole("row").filter({ hasText: OVERDUE }).getByText("Просрочен"),
    ).toBeVisible();
    await settledScreenshot(page, "stock-receipts");
    await expectNoViolations(page, "приёмка");

    // Отгрузка по проекту: накладная ОТГ, резерв проекта уменьшается.
    await page.getByRole("tab", { name: "Отгрузки" }).click();
    await page.getByRole("searchbox", { name: "Номер проекта" }).fill("ПР-2026-099");
    await page.getByRole("button", { name: "Найти резервы" }).click();
    await page
      .getByRole("spinbutton", { name: "Отгрузить, «Скрепление рельсовое КБ-65»" })
      .fill("8");
    await page.getByLabel("Трек-номер").fill("TRK-100");
    await settledScreenshot(page, "stock-shipments");
    await page.getByRole("button", { name: "Отгрузить" }).click();
    await expect(page.getByText(/Отгружено, накладная ОТГ-\d{4}-001/)).toBeVisible();
    await expect(page.getByText("в резерве 12 из 20")).toBeVisible();
    await expectNoViolations(page, "отгрузки");
  });

  test("просроченный заказ — в «Моих задачах» и ведёт на карточку заказа", async ({ page }) => {
    await loginAndWait(page, "supply@demo.example");
    const row = page.getByRole("link", { name: new RegExp(`Просрочен заказ ${OVERDUE}`) });
    await expect(row).toBeVisible();
    await settledScreenshot(page, "queue-overdue");
    await expectNoViolations(page, "Мои задачи с просроченным заказом");
    await row.click();
    await expect(
      page.getByRole("heading", { level: 1, name: `Заказ поставщику ${OVERDUE}` }),
    ).toBeVisible();
    await expect(page.getByText(/просрочка 3 дн\./)).toBeVisible();
    await settledScreenshot(page, "order-overdue");
    await expectNoViolations(page, "карточка просроченного заказа");
  });

  test("роли: менеджер читает склад без действий; администратору раздел «Склад» не положен", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/erp/stock?view=orders");
    await expect(page.getByRole("heading", { level: 1, name: "Склад" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Создать заказ" })).toHaveCount(0);
    await expect(
      page.getByRole("link", { name: new RegExp(`Просрочен заказ ${OVERDUE}`) }),
    ).toHaveCount(0);
    await signOut(page);

    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/erp/stock");
    await expect(page.getByRole("heading", { level: 1, name: "Склад" })).toHaveCount(0);
    await expect(page.getByText(/не положен|нет доступа/i).first()).toBeVisible();
    await expectNoViolations(page, "экран «нет доступа» к складу");
  });
});

test.describe("Склад на телефоне @mobile", () => {
  test.skip(({ isMobile }) => !isMobile, "только проект mobile (390 px)");

  test("@mobile остатки, заказы, карточка ЗП и приёмка — карточками", async ({ page }) => {
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/erp/stock");
    await expect(page.getByRole("heading", { level: 1, name: "Склад" })).toBeVisible();
    await expect(
      page.getByRole("list", { name: "Остатки и резервы по номенклатуре" }),
    ).toBeVisible();
    await settledScreenshot(page, "stock-balances");
    await expectNoViolations(page, "остатки на телефоне");

    await page.getByRole("tab", { name: "Заказы поставщикам" }).click();
    await expect(page.getByRole("list", { name: "Заказы поставщикам" })).toBeVisible();
    await settledScreenshot(page, "stock-orders");
    await expectNoViolations(page, "заказы на телефоне");

    await spaGoto(page, `/erp/stock/${encodeURIComponent(OVERDUE)}`);
    await expect(
      page.getByRole("heading", { level: 1, name: `Заказ поставщику ${OVERDUE}` }),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Журнал заказа" })).toBeVisible();
    await settledScreenshot(page, "order-overdue");
    await expectNoViolations(page, "карточка заказа на телефоне");

    await spaGoto(page, "/erp/stock?view=receipts");
    await expect(
      page.getByRole("list", { name: "Строки подтверждённых заказов, ждущие товара" }),
    ).toBeVisible();
    await settledScreenshot(page, "stock-receipts");
    await expectNoViolations(page, "приёмка на телефоне");

    await spaGoto(page, `/erp/calc/${encodeURIComponent(NUMBER)}`);
    await expect(
      page.getByRole("heading", { level: 1, name: `Расчёт по заявке ${NUMBER}` }),
    ).toBeVisible();
    await settledScreenshot(page, "calc-stock");
    await expectNoViolations(page, "расчёт со складом на телефоне");
  });
});
