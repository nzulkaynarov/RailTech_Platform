import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, screenshot, settledScreenshot, waitForMotionEnd } from "./support/app";

// UX-1c «Данные без мигания» (аудит 2026-10-30, S8–S10; platform-frontend.md §4.1, инвариант 6): смена фильтра и вкладки
// оставляет прежние строки с признаком загрузки, высота блока и границы колонок стоят; «Мои задачи» администратора
// загружаются без сдвига от счётчиков и баннера настройки. Ответы API задержаны на 600 мс, чтобы поймать кадр «во время».
// axe 0 и снимки для PR (`E2E_SCREENSHOT_DIR=docs/screens/ux-1c`).

/** Ключ состояния первого запуска в моке (как в first-run.spec.ts). */
const SETUP_KEY = "rt-pf-mock-setup";

/** Ответы API задержаны на 600 мс; чек-лист настройки — ещё на `setupExtra` (поздний ответ после показа экрана, UX-2b). */
const slowApi = (setupExtra = 0) => `(() => {
  const original = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const path = new URL(url, location.href).pathname;
    if (path.startsWith("/api")) {
      const delay = 600 + (path.startsWith("/api/v1/setup/checklist") ? ${String(setupExtra)} : 0);
      return new Promise((resolve) => setTimeout(resolve, delay)).then(() => original(input, init));
    }
    return original(input, init);
  };
  window.__shifts = [];
  new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) window.__shifts.push(entry.value);
  }).observe({ type: "layout-shift", buffered: true });
})();`;
const SLOW_API = slowApi();

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

/** Высота блока данных и левые границы колонок таблицы в нём (`[]` — список карточек на телефоне). */
async function geometry(page: Page, block: string): Promise<{ height: number; columns: number[] }> {
  return page.evaluate<{ height: number; columns: number[] }>(`(() => {
    const element = document.querySelector(${JSON.stringify(block)});
    if (!element) return { height: 0, columns: [] };
    const columns = [...element.querySelectorAll("table thead th")].map((th) =>
      Math.round(th.getBoundingClientRect().left),
    );
    return { height: Math.round(element.getBoundingClientRect().height), columns };
  })()`);
}

const shiftsSince = (page: Page, from: number) =>
  page.evaluate<number>(
    `window.__shifts.slice(${String(from)}).reduce((sum, value) => sum + value, 0)`,
  );
const shiftCount = (page: Page) => page.evaluate<number>(`window.__shifts.length`);

test.describe("Данные без мигания", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of [1440, 390] as const) {
    test(`Лиды на ${String(width)}: фильтр меняется на месте — прежние строки и полоса загрузки, без скелетона, axe 0`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "all@demo.example");
      await page.addInitScript({ content: SLOW_API });
      await page.goto("/crm/leads");
      await expect(page.getByRole("heading", { level: 1, name: "Лиды" })).toBeVisible();
      const block = ".pf-crm .pf-data-block";
      await expect(page.locator(`${block} [data-pf-skeleton]`)).toHaveCount(0);
      await expect(page.locator(block).getByText("Отказ Демо")).toBeVisible();
      await settledScreenshot(page, "leads-before");
      await expectNoViolations(page, "Лиды до смены фильтра");
      const before = await geometry(page, block);
      const mark = await shiftCount(page);

      await page.locator("main .ant-segmented-item", { hasText: /^Просроченные$/ }).click();
      // во время: прежние строки, блок помечен «идёт загрузка», высота та же
      await expect(page.locator(block)).toHaveAttribute("aria-busy", "true");
      await expect(page.locator(`${block} [data-pf-skeleton]`)).toHaveCount(0);
      await expect(page.locator(block).getByText("Отказ Демо")).toBeVisible();
      expect((await geometry(page, block)).height).toBe(before.height);
      await page.waitForTimeout(250);
      await screenshot(page, "leads-during");

      // после: новые строки, признака нет, колонки на тех же местах, сдвигов нет
      await expect(page.locator(block)).not.toHaveAttribute("aria-busy");
      await expect(page.locator(block).getByText("Отказ Демо")).toHaveCount(0);
      const after = await geometry(page, block);
      after.columns.forEach((x, index) => {
        expect(Math.abs(x - (before.columns[index] ?? x))).toBeLessThanOrEqual(2);
      });
      expect(await shiftsSince(page, mark)).toBeLessThanOrEqual(0.01);
      await settledScreenshot(page, "leads-after");
      await expectNoViolations(page, "Лиды после смены фильтра");
    });

    test(`Документы на ${String(width)}: «Мои / Все» и вкладка — без скелетона и сдвига, axe 0`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "all@demo.example");
      await page.addInitScript({ content: SLOW_API });
      await page.goto("/eds/documents");
      await expect(page.getByRole("heading", { level: 1, name: "Все документы" })).toBeVisible();
      const block = ".pf-docs .pf-data-block";
      await expect(page.locator(block).getByText("Итоги недели по заявкам")).toBeVisible();
      await settledScreenshot(page, "documents");
      await expectNoViolations(page, "Документы");
      const mark = await shiftCount(page);

      await page.locator("main .ant-segmented-item", { hasText: /^Мои$/ }).click();
      await expect(page.locator(block)).toHaveAttribute("aria-busy", "true");
      await expect(page.locator(`${block} [data-pf-skeleton]`)).toHaveCount(0);
      await expect(page.locator(block)).not.toHaveAttribute("aria-busy");
      await page.locator("main .ant-segmented-item", { hasText: /^Все$/ }).click();
      await expect(page.locator(block)).not.toHaveAttribute("aria-busy");
      await expect(page.locator(block).getByText("Итоги недели по заявкам")).toBeVisible();

      const before = await geometry(page, block);
      if (width === 1440) await page.getByRole("tab", { name: "Служебные", exact: true }).click();
      else {
        await page.locator("#pf-docs-kind").click({ force: true });
        await page.locator(".ant-select-item-option", { hasText: /^Служебные$/ }).click();
      }
      await expect(page.locator(`${block} [data-pf-skeleton]`)).toHaveCount(0);
      await expect(page.locator(block)).not.toHaveAttribute("aria-busy");
      await expect(page.locator(block).getByText("Итоги недели по заявкам")).toHaveCount(0);
      const after = await geometry(page, block);
      after.columns.forEach((x, index) => {
        expect(Math.abs(x - (before.columns[index] ?? x))).toBeLessThanOrEqual(2);
      });
      expect(await shiftsSince(page, mark)).toBeLessThanOrEqual(0.01);
      await settledScreenshot(page, "documents-memo");
      await expectNoViolations(page, "Документы, служебные");
    });

    test(`Мои задачи администратора на ${String(width)}: первая загрузка без сдвига от счётчиков и баннера, axe 0`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      // Настройка не завершена — баннер «Настройка Платформы» есть (состояние мока до загрузки, как в first-run.spec)
      const fresh = JSON.stringify({
        needsAdmin: false,
        code: "",
        fresh: true,
        companyCreated: false,
        done: {},
      });
      await page.addInitScript(
        `if (!window.localStorage.getItem(${JSON.stringify(SETUP_KEY)})) window.localStorage.setItem(${JSON.stringify(SETUP_KEY)}, ${JSON.stringify(fresh)});`,
      );
      await page.addInitScript({ content: SLOW_API });
      await page.goto("/login");
      await page.getByLabel("Электронная почта").fill("all@demo.example");
      await page.getByLabel("Пароль").fill("demo-pass-1");
      const mark = await shiftCount(page);
      await page.getByRole("button", { name: "Войти" }).click();
      await expect(page).toHaveURL(/\/dashboard\/queue$/);
      await expect(page.getByRole("region", { name: "Настройка Платформы" })).toBeVisible();
      await expect(
        page.getByRole("heading", { level: 2, name: "Что сделать сейчас" }),
      ).toBeVisible();
      await expect(page.locator(".pf-counter-skel")).toHaveCount(0);
      await page.waitForTimeout(1500);
      expect(await shiftsSince(page, mark)).toBeLessThanOrEqual(0.01);
      await settledScreenshot(page, "queue-admin");
      await expectNoViolations(page, "Мои задачи администратора");
    });
  }

  test("чек-лист ответил после показа экрана: баннер под экраном, готовый экран не сдвигается (UX-2b)", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 900 });
    const fresh = JSON.stringify({
      needsAdmin: false,
      code: "",
      fresh: true,
      companyCreated: false,
      done: {},
    });
    await page.addInitScript(
      `if (!window.localStorage.getItem(${JSON.stringify(SETUP_KEY)})) window.localStorage.setItem(${JSON.stringify(SETUP_KEY)}, ${JSON.stringify(fresh)});`,
    );
    // чек-лист отвечает через 2,1 с — позже предела ожидания 800 мс: экран уже показан
    await page.addInitScript({ content: slowApi(1500) });
    await page.goto("/login");
    await page.getByLabel("Электронная почта").fill("all@demo.example");
    await page.getByLabel("Пароль").fill("demo-pass-1");
    const mark = await shiftCount(page);
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page).toHaveURL(/\/dashboard\/queue$/);
    const banner = page.getByRole("region", { name: "Настройка Платформы" });
    await expect(banner).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(500);
    expect(await shiftsSince(page, mark)).toBeLessThanOrEqual(0.01);
    // баннер — последним в рабочей области, после экрана
    expect(
      await page.evaluate(
        `document.querySelector("#main-content > .pf-setup-banner") === document.querySelector("#main-content").lastElementChild`,
      ),
    ).toBe(true);
    // со следующего перехода — на своём месте сверху
    await page
      .getByRole("navigation", { name: "Модули" })
      .getByRole("link")
      .filter({ hasText: "Документы" })
      .click();
    await expect(page).not.toHaveURL(/\/dashboard\/queue$/);
    await expect(banner).toBeVisible();
    expect(
      await page.evaluate(
        `document.querySelector("#main-content > .pf-setup-banner") === document.querySelector("#main-content").firstElementChild`,
      ),
    ).toBe(true);
  });
});
