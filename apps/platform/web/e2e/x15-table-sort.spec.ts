import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// Х-15: сортировка щелчком по шапке общей таблицы на MSW. Два реестра постраничных списков: «Проекты» (столбцы «Проект»,
// «Срок») и «Лиды» («Последнее»). Порядок — в адресе страницы (`?sort=field` / `-field`), сортирует «сервер» (мок
// принимает параметр так же, как BFF); `aria-sort` и одна стрелка на шапке; чужое поле из адреса игнорируется;
// на 390 px реестр — карточки без шапки, порядок из адреса сохраняется; axe (WCAG 2.1 AA); снимки 1440 и 390.

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

/** Тексты первого столбца таблицы в порядке строк. */
async function firstColumn(page: Page, tableName: string | RegExp): Promise<string[]> {
  return page
    .getByRole("table", { name: tableName })
    .locator("tbody > tr > :first-child a")
    .allTextContents();
}

const sorted = (list: string[]) =>
  [...list].sort((a, b) => a.localeCompare(b, "ru", { numeric: true }));

test.describe("Сортировка по шапке: десктоп", () => {
  test.skip(({ isMobile }) => isMobile, "десктоп; телефон — блок @mobile");

  test("проекты: щелчок по «Проект» → по возрастанию → по убыванию → снят, порядок в адресе и у сервера", async ({
    page,
  }) => {
    await loginAndWait(page, "accountant@demo.example");
    await spaGoto(page, "/eds/projects");
    const table = page.getByRole("table", { name: /Проекты/ });
    await expect(table.locator("tbody > tr").first()).toBeVisible();
    const header = table.getByRole("columnheader", { name: /Проект/ });
    await expect(header).toHaveAttribute("aria-sort", "none");
    await expect(page.locator(".pf-dt-sort-arrow")).toHaveCount(0);

    const asked = page.waitForRequest(
      (r) => r.url().includes("/eds/projects?") && /sort=number(&|$)/.test(r.url()),
    );
    await header.getByRole("button").click();
    await asked;
    await expect(page).toHaveURL(/[?&]sort=number(&|$)/);
    await expect(header).toHaveAttribute("aria-sort", "ascending");
    await expect(page.locator(".pf-dt-sort-arrow")).toHaveCount(1);
    // порядок отдаёт сервер: список читается заново и должен совпасть со своей сортировкой по возрастанию
    await expect
      .poll(async () => {
        const list = await firstColumn(page, /Проекты/);
        return list.join() === sorted(list).join();
      })
      .toBe(true);

    await header.getByRole("button").click();
    await expect(page).toHaveURL(/[?&]sort=-number(&|$)/);
    await expect(header).toHaveAttribute("aria-sort", "descending");
    await expect
      .poll(async () => {
        const list = await firstColumn(page, /Проекты/);
        return list.length > 1 && list.join() === sorted(list).reverse().join();
      })
      .toBe(true);
    await settledScreenshot(page, "x15-projects-sorted-desc");
    await expectNoViolations(page, "проекты, порядок по убыванию");

    // с клавиатуры: Enter на кнопке шапки снимает порядок
    await header.getByRole("button").focus();
    await page.keyboard.press("Enter");
    await expect(page).not.toHaveURL(/sort=/);
    await expect(header).toHaveAttribute("aria-sort", "none");
  });

  test("проекты: пустые сроки — в конце, чужое поле в адресе не сортирует", async ({ page }) => {
    await loginAndWait(page, "accountant@demo.example");
    await spaGoto(page, "/eds/projects?sort=-due_date");
    const table = page.getByRole("table", { name: /Проекты/ });
    await expect(table.locator("tbody > tr").first()).toBeVisible();
    await expect(table.getByRole("columnheader", { name: /Срок/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    const dueCells = (await table.locator("tbody > tr > td:nth-child(6)").allTextContents()).map(
      (text) => text.trim(),
    );
    const firstEmpty = dueCells.indexOf("—");
    if (firstEmpty >= 0) expect(dueCells.slice(firstEmpty).every((c) => c === "—")).toBe(true);

    await spaGoto(page, "/eds/projects?sort=password");
    await expect(table.locator("tbody > tr").first()).toBeVisible();
    await expect(page.locator(".pf-dt-sort-arrow")).toHaveCount(0);
  });

  test("лиды: «Последнее» — по возрастанию и убыванию, параметр уходит серверу", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/crm/leads");
    const table = page.getByRole("table", { name: "Лиды" });
    await expect(table.locator("tbody > tr").first()).toBeVisible();
    const header = table.getByRole("columnheader", { name: /Сообщение/ });
    const asked = page.waitForRequest(
      (r) => /crm\/leads\?/.test(r.url()) && /sort=last_message(&|$)/.test(r.url()),
    );
    await header.getByRole("button").click();
    await asked;
    await expect(header).toHaveAttribute("aria-sort", "ascending");
    await header.getByRole("button").click();
    await expect(page).toHaveURL(/[?&]sort=-last_message(&|$)/);
    await expect(header).toHaveAttribute("aria-sort", "descending");
    await settledScreenshot(page, "x15-leads-sorted-desc");
    await expectNoViolations(page, "лиды, порядок по убыванию");
  });
});

test.describe("Сортировка по шапке: телефон", () => {
  test(
    "проекты карточками: порядок из адреса держится, без прокрутки вбок, axe",
    { tag: "@mobile" },
    async ({ page, isMobile }) => {
      test.skip(!isMobile, "узкий экран — проект mobile");
      await loginAndWait(page, "accountant@demo.example");
      await spaGoto(page, "/eds/projects?sort=-number");
      await expect(
        page
          .getByRole("list", { name: /Проекты/ })
          .locator("li")
          .first(),
      ).toBeVisible();
      await expect(page).toHaveURL(/sort=-number/);
      expect(
        await page.evaluate(
          "document.documentElement.scrollWidth - document.documentElement.clientWidth",
        ),
      ).toBeLessThanOrEqual(0);
      await settledScreenshot(page, "x15-projects-sorted-desc");
      await expectNoViolations(page, "проекты на телефоне");
    },
  );

  test(
    "лиды карточками: порядок из адреса держится, без прокрутки вбок, axe",
    { tag: "@mobile" },
    async ({ page, isMobile }) => {
      test.skip(!isMobile, "узкий экран — проект mobile");
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/crm/leads?sort=-last_message");
      await expect(page.getByRole("heading", { level: 1, name: "Лиды" })).toBeVisible();
      expect(
        await page.evaluate(
          "document.documentElement.scrollWidth - document.documentElement.clientWidth",
        ),
      ).toBeLessThanOrEqual(0);
      await settledScreenshot(page, "x15-leads-sorted-desc");
      await expectNoViolations(page, "лиды на телефоне");
    },
  );
});
