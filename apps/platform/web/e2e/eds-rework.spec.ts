import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import {
  loginAndWait,
  openAvatarMenu,
  settledScreenshot,
  spaGoto,
  waitForMotionEnd,
} from "./support/app";

// «Доработать» в «Моих задачах» автора на MSW (D1-6b): директор возвращает служебку → автор видит «Доработать: СЗ-…» с тем,
// кто и что написал → «Открыть» → форма «Продолжить» (D1-5) → правит → «Отправить на согласование» → строки больше нет.
// axe (WCAG 2.1 AA); снимки 1440 и 390 для PR (`E2E_SCREENSHOT_DIR=<каталог>`); на 390 — строка очереди без горизонтальной
// прокрутки (@mobile).
const WIDTHS = [1440, 390] as const;
const ROW = "Доработать: СЗ-2026/014 · Оплата аренды склада за ноябрь";
const REMARK = "Нужен второй счёт от арендодателя.";

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

/** axe и снимок на обеих ширинах; открытое боковое окно на 390 закрываем, чтобы кадр показывал страницу. */
async function shoot(page: Page, name: string): Promise<void> {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    const drawer = page.getByRole("dialog", { name: "Боковое окно" });
    if (width === 390 && (await drawer.isVisible())) {
      await drawer.getByRole("button", { name: "Скрыть боковое окно" }).click();
      await expect(drawer).toBeHidden();
    }
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

test.describe("Доработать возвращённый документ", () => {
  test.skip(({ isMobile }) => isMobile, "сценарий на десктопе; телефон — блок @mobile");

  test("директор возвращает служебку → у автора «Доработать» → «Открыть» → правка → отправка → строка исчезла", async ({
    page,
  }) => {
    // директор: «Вернуть на доработку» с комментарием
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, `/eds/approvals/${encodeURIComponent("СЗ-2026/014")}`);
    const form = page
      .locator("#pf-context-panel")
      .getByRole("form", { name: "Согласование документа" });
    await expect(page.getByRole("heading", { level: 1, name: "СЗ-2026/014" })).toBeVisible();
    await form.getByLabel("Комментарий").fill(REMARK);
    await form.getByRole("button", { name: "Вернуть на доработку" }).click();
    await expect(
      page.getByText("Документ возвращён на доработку", { exact: true }).first(),
    ).toBeVisible();
    await signOut(page);

    // автор: в «Моих задачах» — строка с тем, кто вернул и что написал
    await loginAndWait(page, "manager@demo.example");
    const queue = page.getByRole("region", { name: "Что сделать сейчас" });
    await expect(queue.getByText(ROW)).toBeVisible();
    await expect(queue.getByText(`Вернул Демо Директоров: ${REMARK}`)).toBeVisible();
    // старая возвращённая служебка автора лежит тут же: у каждой своя строка
    await expect(queue.getByText(/^Доработать: СЗ-2026\/028/)).toBeVisible();
    await expect(page.getByRole("main").getByText(/Менеджер · .* · 4 решения/)).toBeVisible();
    await shoot(page, "queue-rework");

    // «Открыть» ведёт в форму «Продолжить» — текст на месте, тип нельзя менять
    await queue.getByRole("link", { name: `Открыть: ${ROW}` }).click();
    await expect(page).toHaveURL(/\/eds\/new\?draft=/);
    await expect(page.getByRole("heading", { level: 1, name: "Создать документ" })).toBeVisible();
    await expect(page.getByLabel("Тема")).toHaveValue("Оплата аренды склада за ноябрь");
    await expect(page.getByText("Тип нельзя менять после создания.")).toBeVisible();
    await shoot(page, "rework-continue");

    await page.getByLabel("Тема").fill("Оплата аренды склада за ноябрь (два счёта)");
    await page.getByRole("button", { name: "Отправить на согласование" }).click();
    const panel = page.locator("#pf-context-panel");
    await expect(
      panel.getByRole("heading", { level: 3, name: "Оплата аренды склада за ноябрь (два счёта)" }),
    ).toBeVisible();
    await expect(panel.getByText("На согласовании")).toBeVisible();

    // строки «Доработать» по этому документу больше нет, вторая возвращённая служебка осталась
    await spaGoto(page, "/dashboard/queue");
    const again = page.getByRole("region", { name: "Что сделать сейчас" });
    await expect(again.getByText(/^Доработать: СЗ-2026\/028/)).toBeVisible();
    await expect(again.getByText(/^Доработать: СЗ-2026\/014/)).toHaveCount(0);
    await expect(page.getByRole("main").getByText(/Менеджер · .* · 3 решения/)).toBeVisible();
  });

  test("у директора нет чужих «Доработать»: возврат касается только автора", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    const queue = page.getByRole("region", { name: "Что сделать сейчас" });
    await expect(queue.getByText("Наложить резолюцию на письмо ВХ-104/26")).toBeVisible();
    await expect(queue.getByText(/^Доработать:/)).toHaveCount(0);
  });
});

test.describe("Доработать возвращённый документ: телефон", () => {
  test(
    "строка «Доработать» на 390 без горизонтальной прокрутки, «Открыть» ведёт в форму",
    { tag: "@mobile" },
    async ({ page, isMobile }) => {
      test.skip(!isMobile, "узкий экран — проект mobile");
      await loginAndWait(page, "manager@demo.example");
      const queue = page.getByRole("region", { name: "Что сделать сейчас" });
      const row = queue.getByText(/^Доработать: СЗ-2026\/028/);
      await expect(row).toBeVisible();
      const overflow = Number(
        await page.evaluate(
          "document.documentElement.scrollWidth - document.documentElement.clientWidth",
        ),
      );
      expect(overflow).toBeLessThanOrEqual(0);
      await settledScreenshot(page, "mobile-queue-rework");
      await expectNoViolations(page, "мобильная очередь");

      await queue.getByRole("link", { name: /^Открыть: Доработать: СЗ-2026\/028/ }).click();
      await expect(page.getByLabel("Тема")).toHaveValue("Командировка в Самарканд");
    },
  );
});
