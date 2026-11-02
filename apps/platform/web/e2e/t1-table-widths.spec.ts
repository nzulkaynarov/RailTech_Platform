import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import {
  loginAndWait,
  openAvatarMenu,
  settledScreenshot,
  spaGoto,
  waitForMotionEnd,
} from "./support/app";

// T1 «Ширина столбцов без прокрутки на 1440 px» (ресёрч 2026-11-02 «Таблицы», §4.1 и §5 T1; platform-frontend.md §4.2):
// на рабочих списках при 1440 (подменю открыто, окно закрыто) таблица помещается в рабочую область без прокрутки вбок
// на ru, uz и en; заголовок — одна строка (на ru не обрезан, на uz/en обрезанный — с полным текстом в `title`); тег статуса —
// одна строка (длинный — многоточие и `title`). Колонки по-прежнему фиксированы — `stable-data.spec.ts`.
// Снимки 1440, 1920 и 390 и axe 0 — `E2E_SCREENSHOT_DIR=docs/screens/t1`.

/** Рабочие списки с таблицей `.pf-fixed-table`. */
const SCREENS = [
  { name: "inbox", path: "/eds/inbox?status=all" },
  { name: "documents", path: "/eds/documents?scope=all" },
  { name: "approvals", path: "/eds/approvals" },
  { name: "drafts", path: "/eds/drafts?scope=all" },
  { name: "projects", path: "/eds/projects" },
  { name: "payments", path: "/eds/payments" },
  { name: "payments-memos", path: "/eds/payments?show=memos" },
  { name: "requests", path: "/erp/requests" },
  { name: "leads", path: "/crm/leads" },
  { name: "clients", path: "/crm/clients" },
  { name: "stock", path: "/erp/stock" },
  { name: "stock-orders", path: "/erp/stock?view=orders" },
  { name: "stock-receipts", path: "/erp/stock?view=receipts" },
] as const;

/** Самые широкие экраны (ресёрч §5 T1) — снимки и axe. */
const WIDEST = ["inbox", "documents", "approvals", "drafts", "projects", "requests"] as const;

type Fit = {
  /** На сколько px таблица шире своей области прокрутки (0 — помещается). */
  overflow: number;
  /** Заголовки, текст которых не помещается в колонку, и есть ли у них `title` с полным текстом. */
  cutHeaders: { text: string; titled: boolean }[];
  /** Заголовки выше одной строки. */
  tallHeaders: string[];
  /** Теги статуса выше одной строки или обрезанные без `title`. */
  badTags: string[];
};

async function fit(page: Page): Promise<Fit> {
  return page.evaluate<Fit>(`(() => {
    const table = document.querySelector("main table.pf-fixed-table");
    const region = table.parentElement;
    const overflow = Math.max(0, Math.round(table.scrollWidth - region.clientWidth));
    const cutHeaders = [];
    const tallHeaders = [];
    for (const th of table.querySelectorAll("thead th")) {
      const text = th.textContent.trim();
      if (!text || th.querySelector(".pf-sr-only")) continue;
      if (th.scrollWidth > th.clientWidth) cutHeaders.push({ text, titled: th.title === text });
      const style = getComputedStyle(th);
      const inner = th.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
      if (inner > (parseFloat(style.lineHeight) || 22) * 1.5) tallHeaders.push(text);
    }
    const badTags = [];
    for (const tag of table.querySelectorAll("tbody .ant-tag")) {
      // видимый текст тега (скрытая подпись для скринридера — не в счёт)
      const copy = tag.cloneNode(true);
      copy.querySelectorAll(".pf-sr-only").forEach((hidden) => hidden.remove());
      const text = copy.textContent.trim();
      const cut = tag.scrollWidth > tag.clientWidth;
      const cell = tag.closest("td");
      const edge = cell.getBoundingClientRect().right - parseFloat(getComputedStyle(cell).paddingRight);
      const outside = tag.getBoundingClientRect().right > edge + 1;
      if (tag.getBoundingClientRect().height > 26 || outside || (cut && tag.title !== text)) badTags.push(text);
    }
    return { overflow, cutHeaders, tallHeaders, badTags: [...new Set(badTags)] };
  })()`);
}

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

/** Переход внутри SPA и ожидание строк нового экрана (прежняя таблица помечена, чтобы не мерить её). */
async function open(page: Page, path: string, rows = "main table.pf-fixed-table"): Promise<void> {
  await page.evaluate(
    `document.querySelectorAll("main table, main ul").forEach((el) => el.setAttribute("data-t1-old", ""))`,
  );
  await spaGoto(page, path);
  await expect(page.locator("main [data-pf-skeleton]")).toHaveCount(0);
  await expect(page.locator(`${rows}:not([data-t1-old])`).first()).toBeVisible();
}

test.describe("T1 · ширина столбцов", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("1440, подменю открыто: таблицы без прокрутки вбок, заголовки и статусы в одну строку (ru, uz, en)", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "all@demo.example");
    for (const [language, item] of [
      ["ru", null],
      ["uz", "O‘zbekcha"],
      ["en", "English"],
    ] as const) {
      if (item) {
        await openAvatarMenu(page);
        await page.getByRole("menuitem", { name: item }).click();
        await expect(page.locator("html")).toHaveAttribute("lang", language);
      }
      for (const screen of SCREENS) {
        await open(page, screen.path);
        const result = await fit(page);
        const where = `${screen.name} (${language})`;
        expect(result.overflow, `${where}: прокрутка вбок`).toBe(0);
        expect(result.tallHeaders, `${where}: заголовок в две строки`).toEqual([]);
        expect(result.badTags, `${where}: тег статуса`).toEqual([]);
        // Обрезанный заголовок — только с полным текстом в подсказке; на ru заголовки помещаются целиком.
        expect(
          result.cutHeaders.filter((header) => !header.titled || language === "ru"),
          `${where}: обрезанный заголовок`,
        ).toEqual([]);
      }
    }
  });

  for (const width of [1440, 1920] as const) {
    test(`снимки самых широких списков на ${String(width)}, axe 0`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "all@demo.example");
      for (const name of WIDEST) {
        const screen = SCREENS.find((item) => item.name === name);
        if (!screen) throw new Error(name);
        await open(page, screen.path);
        expect((await fit(page)).overflow, `${name}: прокрутка вбок`).toBe(0);
        await settledScreenshot(page, `t1-${name}`);
        await expectNoViolations(page, `${name} на ${String(width)}`);
      }
    });
  }

  test("390: списки — карточки, страница не шире экрана, axe 0", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "all@demo.example");
    for (const name of ["inbox", "documents", "approvals"] as const) {
      const screen = SCREENS.find((item) => item.name === name);
      if (!screen) throw new Error(name);
      await open(page, screen.path, "main ul, main table");
      expect(
        await page.evaluate<number>(
          `document.documentElement.scrollWidth - document.documentElement.clientWidth`,
        ),
        `${name}: страница шире экрана`,
      ).toBeLessThanOrEqual(0);
      await settledScreenshot(page, `t1-${name}`);
      await expectNoViolations(page, `${name} на 390`);
    }
  });
});
