import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";
import { chooseOption } from "./support/fields";
import { expectFitsFrame } from "./support/layout";

// ЕВ-З на MSW: «Настройки · Люди и доступ · Зоны ответственности». Девять зон без людей, директор назначает ответственного
// и основание, администратор заводит зону, сигнал «зона без ответственного» в «Состоянии» и карточка на Главной.
// axe 0 и снимки 1440 и 390 (`E2E_SCREENSHOT_DIR` → docs/screens/evz-zones/).
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

test.describe("ЕВ-З · Зоны ответственности", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("директор назначает ответственного, администратор заводит зону; сигнал на Настройках и Главной", async ({
    page,
  }) => {
    // Директор: на Главной карточка «Зоны без ответственного», в таблице — девять зон без людей
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/dashboard/queue");
    await expect(page.getByText("Зоны без ответственного")).toBeVisible();
    await shoot(page, "zones-home-card");

    await spaGoto(page, "/admin/zones");
    await expect(
      page.getByRole("heading", { level: 1, name: "Зоны ответственности" }),
    ).toBeVisible();
    const finance = page.getByRole("row", { name: /Финансы/ });
    await expect(finance).toContainText("Не назначен");
    await expect(finance).not.toContainText("Нет ответственного");
    await expect(page.getByText("Зон без ответственного: 9")).toBeVisible();
    await expect(page.getByRole("button", { name: "Новая зона" })).toHaveCount(0);
    await shoot(page, "zones-list");
    await expectFitsFrame(page, "zones-list");

    await page.getByRole("button", { name: "Открыть зону «Финансы»" }).click();
    const panel = page.getByRole("region", { name: "Зона «Финансы»" });
    await chooseOption(panel.getByRole("combobox", { name: "Ответственный" }), "Демо Бухгалтеров");
    await panel.getByRole("textbox", { name: "Основание" }).fill("Приказ № 5 от 01.12.2026");
    await shoot(page, "zones-card");
    await panel.getByRole("button", { name: "Сохранить" }).click();
    await expect(page.getByRole("row", { name: /Финансы/ })).toContainText("Демо Бухгалтеров");
    await expect(page.locator(".ant-message-notice")).toHaveCount(0, { timeout: 10_000 });
    await shoot(page, "zones-assigned");
  });

  test("администратор: «Новая зона» из существующих разделов и строка-сигнал в «Состоянии»", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin");
    await expect(page.getByText(/Зон без ответственного: 9/)).toBeVisible();
    await shoot(page, "zones-settings-signal");

    await spaGoto(page, "/admin/zones");
    await page.getByRole("button", { name: "Новая зона" }).first().click();
    const form = page.getByRole("region", { name: "Новая зона" });
    await form.getByRole("textbox", { name: "Название по-русски" }).fill("Качество");
    await form.getByRole("textbox", { name: "Название по-узбекски" }).fill("Sifat");
    await form.getByRole("textbox", { name: "Название по-английски" }).fill("Quality");
    await chooseOption(
      form.getByRole("combobox", { name: "Разделы прав зоны" }),
      "Контакты · Контрагенты, создать заявку",
    );
    // выпадающий список множественного выбора закрываем: снимок и axe — по форме, а не по открытому списку
    await form.getByRole("heading", { name: "Новая зона" }).click();
    await expect(page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden)")).toHaveCount(
      0,
    );
    await shoot(page, "zones-new");
    await form.getByRole("button", { name: "Создать" }).click();
    await expect(page.getByRole("row", { name: /Качество/ })).toContainText("Не назначен");
    await expect(page.locator(".ant-message-notice")).toHaveCount(0, { timeout: 10_000 });
    await shoot(page, "zones-created");
  });
});
