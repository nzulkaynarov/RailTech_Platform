import { expect, test, type Page } from "@playwright/test";

import { expectNoViolations } from "./support/axe";
import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";

// ЕВ-1а на MSW: четыре списка в общей рамке (RegistryTable) — Журнал, Сотрудники, Обращения, Все шаблоны.
// Факт, а не вид: выбранная строка закрашена (раньше у Журнала и Сотрудников селектор был мёртвый), шапка таблицы
// с подложкой и заголовками влево, строки разделены линиями. Снимки 1440 и 390, axe 0 — E2E_SCREENSHOT_DIR.
const WIDTHS = [1440, 390] as const;

interface Look {
  headBackground: string;
  headAlign: string;
  rowLine: string;
  cardBorder: string;
}

async function look(page: Page): Promise<Look> {
  return page.evaluate<Look>(`(() => {
    const table = document.querySelector("table.pf-dt-table");
    if (!table) throw new Error("no framed table on the screen");
    const th = table.querySelector("thead th");
    const td = table.querySelector("tbody tr:not(:last-child) td");
    const card = table.closest(".pf-reg");
    if (!th || !td || !card) throw new Error("table is not inside the shared frame");
    return {
      headBackground: getComputedStyle(th).backgroundColor,
      headAlign: getComputedStyle(th).textAlign,
      rowLine: getComputedStyle(td).borderBottomWidth,
      cardBorder: getComputedStyle(card).borderTopWidth,
    };
  })()`);
}

async function selectedBackground(page: Page): Promise<string> {
  return page.evaluate<string>(`(() => {
    const cell = document.querySelector("table.pf-dt-table tr[data-selected='true'] td");
    if (!cell) throw new Error("no selected row");
    return getComputedStyle(cell).backgroundColor;
  })()`);
}

async function evidence(page: Page, name: string): Promise<void> {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
    await expect(page.locator(".pf-reg")).toBeVisible();
    await expectNoViolations(page, `${name} ${String(width)}`);
    await settledScreenshot(page, name);
    // нет горизонтальной прокрутки страницы
    const overflow = await page.evaluate<number>(
      "document.documentElement.scrollWidth - document.documentElement.clientWidth",
    );
    expect(overflow, `${name} ${String(width)}`).toBeLessThanOrEqual(0);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

test.describe("Общая рамка списка", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("Журнал: рамка, шапка, линии и закрашенная выбранная запись", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/audit");
    const table = page.getByRole("table", { name: "Записи журнала аудита" });
    await expect(table.getByRole("row")).toHaveCount(14);
    expect(await look(page)).toEqual({
      headBackground: "rgb(241, 245, 249)",
      headAlign: "left",
      rowLine: "1px",
      cardBorder: "1px",
    });
    await evidence(page, "audit");
    await table.getByRole("link").first().click();
    await expect(page.locator("table.pf-dt-table tr[data-selected='true']")).toHaveCount(1);
    expect(await selectedBackground(page)).toBe("rgb(239, 246, 255)");
    await settledScreenshot(page, "audit-selected");
  });

  test("Сотрудники: выбранная строка закрашена", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/org?view=list");
    const table = page.getByRole("table", { name: "Сотрудники" });
    await expect(table.getByRole("row").nth(1)).toBeVisible();
    expect((await look(page)).headAlign).toBe("left");
    await evidence(page, "org");
    await table.getByRole("link").first().click();
    await expect(page.locator("table.pf-dt-table tr[data-selected='true']")).toHaveCount(1);
    expect(await selectedBackground(page)).toBe("rgb(239, 246, 255)");
    await settledScreenshot(page, "org-selected");
  });

  test("Обращения: рамка со строками и выбранная строка; пустой список — состояние внутри рамки", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    // пусто: состояние внутри рамки, пустой таблицы нет (карточка открыта сбоку — на экране 1440 видно обе)
    await page.goto("/admin/tickets/TK-0001?panel=open&tab=card");
    const emptyFrame = page.locator(".pf-reg");
    await expect(emptyFrame.getByRole("heading", { level: 2 })).toBeVisible();
    await expect(emptyFrame.getByRole("table")).toHaveCount(0);
    // три обращения в хранилище моков — список без открытой карточки
    const at = "2026-11-20T09:00:00Z";
    const ticket = (seq: number, subject: string, status: string, body: string) => ({
      seq,
      subject,
      status,
      authorId: "u-demo",
      authorName: "Демо Менеджеров",
      body,
      messages: [],
      createdAt: at,
      updatedAt: at,
    });
    const stored = {
      tickets: [
        ticket(1, "access", "new", "Нужен доступ к документам"),
        ticket(2, "error", "in_progress", "Не открывается шаблон"),
        ticket(3, "other", "resolved", "Вопрос по уведомлениям"),
      ],
      notes: [],
      nextTicket: 4,
      nextNote: 1,
    };
    await page.evaluate(
      `window.localStorage.setItem("rt-pf-mock-tickets", ${JSON.stringify(JSON.stringify(stored))})`,
    );
    await page.goto("/admin/tickets/TK-0002");
    const table = page.locator("table.pf-dt-table");
    await expect(table.getByRole("row")).toHaveCount(4);
    expect(await look(page)).toMatchObject({ headAlign: "left", rowLine: "1px" });
    await expect(page.locator("tr[data-selected='true']")).toHaveCount(1);
    expect(await selectedBackground(page)).toBe("rgb(239, 246, 255)");
    await evidence(page, "tickets");
  });

  test("Все шаблоны: рамка вместо голой таблицы", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/admin/templates");
    const table = page.getByRole("table", { name: "Шаблоны всех разделов" });
    await expect(
      table.getByRole("link", { name: "Коммерческое предложение" }).first(),
    ).toBeVisible();
    expect(await look(page)).toMatchObject({ headAlign: "left", rowLine: "1px" });
    await evidence(page, "templates");
  });
});
