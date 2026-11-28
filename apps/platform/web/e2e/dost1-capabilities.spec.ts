import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ДОСТ-1 «Видеть, что может каждый» (шаг 1 модели доступа, только чтение), владелец 2026-11-27: «Кто что может» первым видом
// «Сотрудников и возможностей», карточка человека, «Мои возможности» в профиле, «Нет возможности» вместо «Нет доступа».
// axe 0 и снимки 1440 и 390 для PR (`E2E_SCREENSHOT_DIR=docs/screens/dost1`). Все четыре экрана — на MSW.
const WIDTHS = [1440, 390] as const;
const PANEL = "#pf-context-panel";

async function h1(page: Page, name: string): Promise<void> {
  await expect(page.getByRole("heading", { level: 1, name, exact: true })).toBeVisible();
}

async function openMatrix(page: Page): Promise<void> {
  await spaGoto(page, "/admin/org?view=matrix");
  await h1(page, "Сотрудники");
  await expect(page.getByTestId("cap-matrix")).toBeVisible();
}

test.describe("Кто что может", () => {
  test("таблица: строки по шагам сделки, уровни, подпись и «отвечает за», переключатель на список", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openMatrix(page);
    const table = page.getByRole("region", { name: "Что может каждый сотрудник" });
    // шаги сделки и сами возможности
    for (const group of [
      "Лиды и клиенты",
      "Заявки и расчёт",
      "КП и договор",
      "Оплата и документы",
    ]) {
      await expect(table.getByRole("button", { name: new RegExp(group) })).toBeVisible();
    }
    // область раскрывается в возможности
    await expect(table.getByRole("rowheader", { name: "Договор", exact: true })).toHaveCount(0);
    await table.getByRole("button", { name: /КП и договор/ }).click();
    await expect(table.getByRole("rowheader", { name: "Договор", exact: true })).toBeVisible();
    await table.getByRole("button", { name: /Оплата и документы/ }).click();
    // бухгалтер решает по оплатам, менеджер — нет
    const payments = table.locator('[data-capability="payments"]');
    await expect(payments.getByText("Решать").first()).toBeVisible();
    // подпись и «отвечает за» — отдельно от возможностей
    await expect(table.getByTestId("cap-row-signing")).toBeVisible();
    await expect(table.getByTestId("cap-row-zones")).toBeVisible();
    // виза без права подписи — не предупреждение (в демо-данных других предупреждений нет)
    await expect(page.getByTestId("cap-warnings")).toHaveCount(0);

    await page.getByText("Списком", { exact: true }).click();
    await expect(
      page.getByRole("link", { name: "Открыть карточку: Демо Менеджеров" }),
    ).toBeVisible();
    await expect(page.getByTestId("cap-matrix")).toHaveCount(0);
    await page.getByText("Кто что может", { exact: true }).click();
    await expect(page.getByTestId("cap-matrix")).toBeVisible();
  });

  test("директор видит таблицу, но не меняет роли", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await openMatrix(page);
    await expect(page.getByRole("button", { name: "Пригласить сотрудника" })).toHaveCount(0);
  });

  for (const width of WIDTHS) {
    test(`снимок и axe: таблица ${String(width)}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "admin@demo.example");
      await openMatrix(page);
      await expectNoViolations(page, `matrix ${String(width)}`);
      await settledScreenshot(page, "matrix");
      // на 390 страница не ползёт вбок: прокручивается только сама таблица
      const overflow = await page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth",
      );
      expect(overflow).toBe(false);
    });
  }
});

test.describe("Что может этот человек", () => {
  test("окно: короткий итог и «Открыть», выдача — прежняя, ролями; страница человека — таблица и блоки", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });
    await loginAndWait(page, "admin@demo.example");
    await openMatrix(page);
    await page.getByRole("link", { name: "Открыть: Демо Менеджеров" }).click();
    const panel = page.locator(PANEL);
    const card = panel.getByTestId("cap-card");
    await expect(
      card.getByRole("heading", { level: 3, name: "Что может этот человек" }),
    ).toBeVisible();
    await expect(card.getByText("Что делает")).toHaveCount(0);
    await expect(card.getByTestId("cap-warnings")).toHaveCount(0);
    await expect(card.getByTestId("cap-summary").locator("[data-line]").first()).toBeVisible();
    await expect(card.getByTestId("cap-rows")).toHaveCount(0);
    // выдача прав — прежняя: ссылка ведёт к форме ролей на этой же карточке
    await card.getByRole("button", { name: "Изменить через роли (до следующего шага)" }).click();
    await expect(panel.getByRole("button", { name: "Сохранить роли" })).toBeVisible();

    await card.getByRole("link", { name: "Открыть" }).click();
    const full = page.getByTestId("cap-page");
    await expect(full.getByRole("heading", { level: 1, name: "Демо Менеджеров" })).toBeVisible();
    // «Договор» у менеджера — смотреть; раскрыть: действия «подготовка» выключены
    const contract = full.locator('[data-capability="contract"]');
    await expect(contract.getByText("Смотреть")).toBeVisible();
    await contract.getByRole("button").click();
    await expect(
      contract.getByText("готовить договор по шаблону и отправлять клиенту"),
    ).toBeVisible();
    await expect(contract.locator(".pf-cap-action-off").first()).toBeVisible();
    await expect(contract.getByText(/Из роли:/)).toBeVisible();
    // подпись, «отвечает за», замещение — честные блоки справа
    await expect(full.getByTestId("cap-signing")).toBeVisible();
    await expect(full.getByTestId("cap-zones")).toBeVisible();
    await expect(full.getByTestId("cap-deputy")).toBeVisible();
  });

  test("у директора ссылки «Изменить через роли» нет", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await openMatrix(page);
    await page.getByRole("link", { name: "Открыть: Демо Менеджеров" }).click();
    await expect(page.locator(PANEL).getByTestId("cap-card")).toBeVisible();
    await expect(page.getByTestId("cap-change-link")).toHaveCount(0);
  });

  for (const width of WIDTHS) {
    test(`axe: карточка ${String(width)}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin/org?employee=u-demo-manager&panel=open");
      await expect(page.getByTestId("cap-card")).toBeVisible();
      await expectNoViolations(page, `card ${String(width)}`);
      await settledScreenshot(page, "card-open");
    });
  }
  for (const width of WIDTHS) {
    test(`axe: страница человека ${String(width)}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin/org/u-demo-manager");
      await expect(page.getByTestId("cap-page")).toBeVisible();
      await expect(page.getByTestId("cap-rows")).toBeVisible();
      await expectNoViolations(page, `person page ${String(width)}`);
      await settledScreenshot(page, "person-page");
    });
  }

  test("таблица на 8 человек помещается в 1512 без горизонтальной прокрутки и в один экран", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1512, height: 982 });
    await loginAndWait(page, "admin@demo.example");
    const roles = ["1", "2", "3", "4", "5", "6", "3", "6"];
    const items = roles.map((role, i) => ({
      id: `u-x${String(i)}`,
      name: `Сотрудник Номер${String(i)} Длиннофамильный`,
      initials: "СН",
      email: `x${String(i)}@demo.example`,
      position: "Старший специалист по работе с ключевыми клиентами",
      role_ids: [role],
      access: { crm: true, erp: true },
      status: "active",
      telegram_linked: true,
      telegram: "linked",
      erp_sync: "ok",
    }));
    await page.evaluate(
      `window.localStorage.setItem("rt-pf-mock-employees", ${JSON.stringify(JSON.stringify(items))});`,
    );
    await spaGoto(page, "/admin/org?view=matrix");
    await expect(page.getByTestId("cap-matrix")).toBeVisible();
    const wrap = page.getByRole("region", { name: "Что может каждый сотрудник" });
    const scrolls = await wrap.evaluate((el) => el.scrollWidth > el.clientWidth);
    expect(scrolls).toBe(false);
    const box = await wrap.boundingBox();
    expect((box?.y ?? 0) + (box?.height ?? 0)).toBeLessThanOrEqual(982);
  });
});

test.describe("Мои возможности", () => {
  test("профиль: те же данные про себя, только чтение, «Попросить возможность»", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/me?part=capabilities");
    const mine = page.getByTestId("my-capabilities");
    await expect(mine).toBeVisible();
    await expect(mine).not.toContainText("Что я делаю");
    await expect(mine.locator('[data-capability="leads"]').getByText("Работать")).toBeVisible();
    await expect(mine.locator('[data-capability="staff"]').getByText("Нет")).toBeVisible();
    // свои подпись и зоны читает любой сотрудник (у менеджера в демо — доверенность на письма и КП)
    await expect(mine.getByTestId("cap-signing")).toContainText("по доверенности");
    await expect(mine.getByTestId("cap-zones")).toBeVisible();
    await mine.getByRole("button", { name: "Попросить возможность" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
  });

  for (const width of WIDTHS) {
    test(`снимок и axe: профиль ${String(width)}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/me?part=capabilities");
      await expect(page.getByTestId("my-capabilities")).toBeVisible();
      await expectNoViolations(page, `mine ${String(width)}`);
      await settledScreenshot(page, "mine");
    });
  }
});

test.describe("Нет возможности", () => {
  test("«Нет доступа» называет недостающую возможность и отправляет просьбу", async ({ page }) => {
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/admin/org");
    await h1(page, "Нет доступа");
    await expect(
      page.getByRole("heading", { level: 2, name: "«Сотрудники и возможности» вам не выдано" }),
    ).toBeVisible();
    await expect(page.getByText(/Сейчас у вас — «Нет»/)).toBeVisible();
    await expect(page.getByText(/Выдают возможности: .*Демо Админов/)).toBeVisible();
    await page.getByRole("button", { name: "Попросить возможность" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("textbox")).toHaveValue(/«Сотрудники и возможности»: смотреть/);
  });

  for (const width of WIDTHS) {
    test(`снимок и axe: нет возможности ${String(width)}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/admin/org");
      await h1(page, "Нет доступа");
      await expect(page.getByText(/Выдают возможности: .*Демо Админов/)).toBeVisible();
      await expectNoViolations(page, `denied ${String(width)}`);
      await settledScreenshot(page, "denied");
    });
  }
});
