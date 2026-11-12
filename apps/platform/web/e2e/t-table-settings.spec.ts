import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// «Т» плана 2026-11-12 — настройка таблиц сотрудником (TanStack Table, ресёрч 2026-11-02 «Таблицы» §4.2) на «Все документы»:
// ширина мышью за границу заголовка и «Уже/Шире» в «Столбцах», скрыть, переставить, закрепить слева; настройки переживают
// перезагрузку (браузер, на пользователя), «Сбросить» возвращает вид по умолчанию; axe 0 с открытым меню.

async function openList(page: Page): Promise<void> {
  await spaGoto(page, "/eds/documents?scope=all");
  await expect(page.getByRole("heading", { level: 1, name: "Все документы" })).toBeVisible();
  await expect(page.getByRole("table")).toBeVisible();
}

async function headers(page: Page): Promise<string[]> {
  return (await page.getByRole("columnheader").allTextContents()).map((text) => text.trim());
}

async function headerWidth(page: Page, name: string): Promise<number> {
  const box = await page.getByRole("columnheader", { name, exact: true }).boundingBox();
  return Math.round(box?.width ?? 0);
}

function menu(page: Page) {
  return page.getByRole("group", { name: "Столбцы" });
}

test.describe("Т · настройка столбцов", () => {
  test.skip(({ isMobile }) => isMobile, "на телефоне списки — карточки");

  test("ширина мышью и с клавиатуры, скрыть, переставить, закрепить — сохраняется; «Сбросить»", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "director@demo.example");
    await openList(page);
    const before = await headers(page);
    expect(before.slice(0, 3)).toEqual(["Номер", "Тема", "Статус"]);

    // мышь: тянем правую границу «Статуса» на 60 px
    const status = page.getByRole("columnheader", { name: "Статус", exact: true });
    const box = await status.boundingBox();
    if (!box) throw new Error("нет заголовка «Статус»");
    const startWidth = Math.round(box.width);
    await page.mouse.move(box.x + box.width - 1, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width + 59, box.y + box.height / 2, { steps: 6 });
    await page.mouse.up();
    await expect.poll(() => headerWidth(page, "Статус")).toBeGreaterThan(startWidth + 40);

    // клавиатура: «Столбцы» → «Шире: Нужно до»
    await page.getByRole("button", { name: "Столбцы" }).click();
    const settings = menu(page);
    await expect(settings).toBeVisible();
    const dueBefore = await headerWidth(page, "Нужно до");
    await settings.getByRole("button", { name: "Шире: Нужно до" }).click();
    await expect.poll(() => headerWidth(page, "Нужно до")).toBeGreaterThan(dueBefore + 8);

    // скрыть «Создан», «Сумма» выше, закрепить «Тему»
    await settings.getByRole("checkbox", { name: "Создан" }).uncheck();
    await settings.getByRole("button", { name: "Выше: Сумма" }).click();
    await settings.getByRole("button", { name: "Закрепить слева: Тема" }).click();
    await expect(settings.getByRole("checkbox", { name: "Номер" })).toBeDisabled();
    await waitForMotionEnd(page);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(
      results.violations.map(
        (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`,
      ),
    ).toEqual([]);
    await settledScreenshot(page, "columns-menu");
    await page.keyboard.press("Escape");

    const changed = await headers(page);
    expect(changed[0]).toBe("Тема");
    expect(changed).not.toContain("Создан");
    expect(changed.indexOf("Сумма")).toBeLessThan(changed.indexOf("Статус"));

    // перезагрузка: настройки на месте
    await page.reload();
    await expect(page.getByRole("table")).toBeVisible();
    expect(await headers(page)).toEqual(changed);
    expect(await headerWidth(page, "Статус")).toBeGreaterThan(startWidth + 40);
    await settledScreenshot(page, "columns-custom");

    // «Сбросить» — вид по умолчанию
    await page.getByRole("button", { name: "Столбцы" }).click();
    await menu(page).getByRole("button", { name: "Сбросить" }).click();
    await expect.poll(() => headers(page)).toEqual(before);
    expect(Math.abs((await headerWidth(page, "Статус")) - startWidth)).toBeLessThanOrEqual(1);
  });
});
