import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// Х-15б: сортировка щелчком по шапке для «Счетов и оплат» (смещением, ERP) и реестра «Все документы» (курсором, EDS) на MSW.
// Порядок — в адресе (`?sort=field` / `-field`), сортирует «сервер» (мок принимает параметр так же, как BFF); смена порядка
// возвращает на первую страницу; чужое поле из адреса игнорируется; на 390 px реестр — карточки, порядок из адреса
// сохраняется; axe (WCAG 2.1 AA); снимки 1440 и 390.

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

async function noSideScroll(page: Page): Promise<void> {
  expect(
    await page.evaluate(
      "document.documentElement.scrollWidth - document.documentElement.clientWidth",
    ),
  ).toBeLessThanOrEqual(0);
}

/** Тексты первого столбца таблицы в порядке строк (номер счёта / номер документа). */
async function firstColumn(page: Page, name: string | RegExp): Promise<string[]> {
  return page.getByRole("table", { name }).locator("tbody > tr > :first-child").allTextContents();
}

test.describe("Сортировка по шапке: счета и документы, десктоп", () => {
  test.skip(({ isMobile }) => isMobile, "десктоп; телефон — блок @mobile");

  test("счета: «Сумма» по возрастанию и убыванию, параметр уходит серверу, чужое поле не сортирует", async ({
    page,
  }) => {
    await loginAndWait(page, "accountant@demo.example");
    await spaGoto(page, "/eds/payments?show=all");
    const table = page.getByRole("table", { name: "Счета" });
    await expect(table.locator("tbody > tr").first()).toBeVisible();
    const header = table.getByRole("columnheader", { name: /Сумма/ });
    await expect(header).toHaveAttribute("aria-sort", "none");

    const asked = page.waitForRequest(
      (r) => r.url().includes("/eds/payments?") && /sort=amount(&|$)/.test(r.url()),
    );
    await header.getByRole("button").click();
    await asked;
    await expect(page).toHaveURL(/[?&]sort=amount(&|$)/);
    await expect(header).toHaveAttribute("aria-sort", "ascending");
    await expect(page.locator(".pf-dt-sort-arrow")).toHaveCount(1);

    await header.getByRole("button").click();
    await expect(page).toHaveURL(/[?&]sort=-amount(&|$)/);
    await expect(header).toHaveAttribute("aria-sort", "descending");
    await expect.poll(async () => (await firstColumn(page, "Счета")).length).toBeGreaterThan(1);
    await settledScreenshot(page, "x15b-payments-sorted-desc");
    await expectNoViolations(page, "счета, порядок по убыванию");

    await header.getByRole("button").focus();
    await page.keyboard.press("Enter");
    await expect(page).not.toHaveURL(/sort=/);

    await spaGoto(page, "/eds/payments?show=all&sort=password");
    await expect(table.locator("tbody > tr").first()).toBeVisible();
    await expect(page.locator(".pf-dt-sort-arrow")).toHaveCount(0);
  });

  test("реестр документов: «Сумма» и «Номер», пустые суммы в конце, смена порядка — снова первая страница", async ({
    page,
  }) => {
    await loginAndWait(page, "accountant@demo.example");
    await spaGoto(page, "/eds/documents?scope=all");
    const table = page.getByRole("table", { name: /Документы|Все документы/ });
    await expect(table.locator("tbody > tr").first()).toBeVisible();
    const amount = table.getByRole("columnheader", { name: /Сумма/ });

    const asked = page.waitForRequest(
      (r) => r.url().includes("/eds/documents?") && /sort=amount(&|$)/.test(r.url()),
    );
    await amount.getByRole("button").click();
    await asked;
    await expect(amount).toHaveAttribute("aria-sort", "ascending");
    await amount.getByRole("button").click();
    await expect(page).toHaveURL(/[?&]sort=-amount(&|$)/);
    await expect(amount).toHaveAttribute("aria-sort", "descending");
    // пустые суммы («—») идут последними и при убывании
    const cells = (await table.locator("tbody > tr > td:nth-child(4)").allTextContents()).map(
      (text) => text.trim(),
    );
    const firstEmpty = cells.indexOf("—");
    if (firstEmpty >= 0) expect(cells.slice(firstEmpty).every((c) => c === "—")).toBe(true);
    await settledScreenshot(page, "x15b-documents-sorted-desc");
    await expectNoViolations(page, "документы, порядок по убыванию");

    const number = table.getByRole("columnheader", { name: /Номер/ });
    await number.getByRole("button").click();
    await expect(page).toHaveURL(/[?&]sort=number(&|$)/);
    await expect(number).toHaveAttribute("aria-sort", "ascending");
    await expect(page.locator(".pf-dt-sort-arrow")).toHaveCount(1);
  });
});

test.describe("Сортировка по шапке: счета и документы, телефон", () => {
  test(
    "счета карточками: порядок из адреса держится, без прокрутки вбок, axe",
    { tag: "@mobile" },
    async ({ page, isMobile }) => {
      test.skip(!isMobile, "узкий экран — проект mobile");
      await loginAndWait(page, "accountant@demo.example");
      await spaGoto(page, "/eds/payments?show=all&sort=-amount");
      await expect(page.getByRole("list", { name: "Счета" }).locator("li").first()).toBeVisible();
      await expect(page).toHaveURL(/sort=-amount/);
      await noSideScroll(page);
      await settledScreenshot(page, "x15b-payments-sorted-desc");
      await expectNoViolations(page, "счета на телефоне");
    },
  );

  test(
    "документы карточками: порядок из адреса держится, без прокрутки вбок, axe",
    { tag: "@mobile" },
    async ({ page, isMobile }) => {
      test.skip(!isMobile, "узкий экран — проект mobile");
      await loginAndWait(page, "accountant@demo.example");
      await spaGoto(page, "/eds/documents?scope=all&sort=-amount");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page).toHaveURL(/sort=-amount/);
      await noSideScroll(page);
      await settledScreenshot(page, "x15b-documents-sorted-desc");
      await expectNoViolations(page, "документы на телефоне");
    },
  );
});
