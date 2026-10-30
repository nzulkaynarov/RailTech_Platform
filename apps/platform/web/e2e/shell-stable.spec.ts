import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, waitForMotionEnd } from "./support/app";

// UX-1a «Оболочка не меняет ширину сама» (аудит 2026-10-30, S1–S4, S12; решение владельца 2026-10-30, п. 2): карточка
// открывает окно поверх, рабочая область не сужается; рядом — только булавкой и если остаётся ≥ 760 px; булавка не
// пересоздаёт содержимое окна; подменю одно на все разделы. axe 0 и снимки для PR (`E2E_SCREENSHOT_DIR=docs/screens/ux-1a`).
const LETTER = "/eds/inbox/%D0%92%D0%A5-104%2F26";

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

const mainWidth = (page: Page) =>
  page.evaluate<number>(`document.getElementById("main-content").getBoundingClientRect().width`);

test.describe("Стабильная оболочка", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of [1440, 1280] as const) {
    test(`карточка письма на ${String(width)}: окно поверх, булавка — рядом без потери содержимого, axe 0`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "all@demo.example");
      const menu = page.getByRole("navigation", { name: "Разделы модуля" });
      const panel = page.getByRole("complementary", { name: "Боковое окно" });

      await page.goto("/eds/inbox");
      await expect(page.getByRole("heading", { level: 1, name: "Входящие письма" })).toBeVisible();
      const listWidth = await mainWidth(page);

      // карточка: окно открыто поверх, ширина рабочей области та же, реквизиты целиком
      await page.goto(LETTER);
      await expect(page.getByRole("heading", { level: 1, name: "Письмо ВХ-104/26" })).toBeVisible();
      await expect(panel).toBeVisible();
      await expect(panel).toHaveClass(/pf-panel-overlay/);
      await expect(panel).toHaveCSS("width", "440px");
      expect(await mainWidth(page)).toBe(listWidth);
      await settledScreenshot(page, "letter-overlay");
      await expectNoViolations(page, "карточка, окно поверх");

      // булавка; на 1440 с подменю места мало — окно остаётся поверх, пока подменю не свернуть
      if (await menu.isVisible()) {
        await page.getByRole("button", { name: "Закрепить рядом с таблицей" }).click();
        await expect(panel).toHaveClass(/pf-panel-overlay/);
        await page.keyboard.press("Control+Backslash");
        await expect(menu).toHaveCount(0);
      } else {
        await page.getByRole("button", { name: "Закрепить рядом с таблицей" }).click();
      }
      await expect(panel).toHaveClass(/pf-panel-docked/);
      const docked = await mainWidth(page);
      expect(docked).toBeGreaterThanOrEqual(760);
      // реквизиты не сжимаются до букв: сетка карточки считается от её ширины — либо одна колонка, либо основной ≥ 540 px
      const columns = await page.evaluate<string>(
        `getComputedStyle(document.querySelector(".pf-letters-grid")).gridTemplateColumns`,
      );
      expect(Number.parseFloat(columns.split(" ")[0] ?? "0")).toBeGreaterThanOrEqual(540);
      await settledScreenshot(page, "letter-docked");
      await expectNoViolations(page, "карточка, окно рядом");
    });
  }

  test("Расчёт на 1440: подменю как в других разделах, ширина рабочей области та же, axe 0", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "all@demo.example");
    const menu = page.getByRole("navigation", { name: "Разделы модуля" });
    await page.goto("/eds/inbox");
    await expect(menu).toBeVisible();
    const before = await mainWidth(page);
    await page.goto("/erp/calc");
    await expect(page.getByRole("heading", { level: 1, name: "Мои расчёты" })).toBeVisible();
    await expect(menu).toBeVisible();
    expect(await mainWidth(page)).toBe(before);
    await settledScreenshot(page, "calc-menu");
    await expectNoViolations(page, "Расчёт с подменю");
  });

  test("карточка письма на 390: окно — Drawer, без горизонтальной прокрутки, axe 0", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "all@demo.example");
    await page.goto(LETTER);
    await expect(page.getByRole("heading", { level: 1, name: "Письмо ВХ-104/26" })).toBeVisible();
    const scroll = await page.evaluate<number>(
      `document.documentElement.scrollWidth - document.documentElement.clientWidth`,
    );
    expect(scroll).toBeLessThanOrEqual(0);
    await settledScreenshot(page, "letter");
    await expectNoViolations(page, "карточка 390");
  });
});
