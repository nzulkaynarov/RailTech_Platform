import { appendFileSync } from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, screenshot, spaGoto, waitForMotionEnd } from "./support/app";
import { pickRowAction } from "./support/rowActions";

// ШАБЛ-1: шаблон скачивается в Word и PDF, правки загружаются обратно через «что изменилось».
// Снимки 1512, 1440 и 390 с axe — E2E_SCREENSHOT_DIR (docs/screens/shabl1).
const WIDTHS = [1512, 1440, 390] as const;

async function expectNoViolations(page: Page, context: string): Promise<void> {
  await waitForMotionEnd(page);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (dir) {
    appendFileSync(
      `${dir}/axe-results.txt`,
      `${context}: axe violations=${String(results.violations.length)}\n`,
    );
  }
  expect(
    results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`),
    context,
  ).toEqual([]);
}

/** «Загрузить из Word»: кнопка открывает выбор файла — подставляем свой. */
async function upload(page: Page, text: string): Promise<void> {
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Загрузить из Word" }).click();
  await (await chooser).setFiles(file(text));
}

const file = (text: string) => ({
  name: "Правки юриста.docx",
  mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  buffer: Buffer.from(text),
});

for (const width of WIDTHS) {
  test.describe(`шаблон в Word, ${String(width)}`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 960 });
      await loginAndWait(page, "admin@demo.example");
    });

    test("редактор: разметка скрыта, Word и PDF под рукой; загрузка показывает, что изменилось", async ({
      page,
    }) => {
      await spaGoto(page, "/admin/templates?tab=documents");
      await pickRowAction(page, "Договор поставки (наш)", "Изменить");
      const editor = page.getByRole("region", { name: "Изменить шаблон документа" });
      await expect(editor.getByRole("button", { name: "Скачать Word" })).toBeVisible();
      await expect(editor.getByRole("button", { name: "Загрузить из Word" })).toBeVisible();
      await expect(editor.getByLabel(/^Текст шаблона \(HTML\)/)).toBeHidden();
      await expect(
        editor.getByRole("img", { name: /Образец документа по шаблону/ }).first(),
      ).toBeVisible();
      await expect(editor.getByRole("button", { name: "Скачать PDF" })).toBeVisible();
      await expect(editor.locator(".pf-co-sample [aria-busy='false']")).toBeVisible();
      await page.waitForTimeout(500);
      await screenshot(page, "editor");
      await expectNoViolations(page, `editor ${String(width)}`);

      const download = page.waitForEvent("download");
      await editor.getByRole("button", { name: "Скачать Word" }).click();
      expect((await download).suggestedFilename()).toBe(
        "Договор поставки (наш), ред. 1 — проект.docx",
      );

      await upload(page, "UNKNOWN IMAGES");
      const sheet = page.getByRole("dialog", { name: /Что изменилось · RU/ });
      await expect(sheet.getByText("Неизвестные поля: 1")).toBeVisible();
      await expect(sheet.getByText("Пункт 1 · изменён")).toBeVisible();
      await expect(sheet.getByText("{{warehouse.name}}")).toBeVisible();
      await expect(sheet.getByRole("button", { name: "Принять изменения" })).toBeEnabled();
      await page.waitForTimeout(500);
      await screenshot(page, "changes");
      await expectNoViolations(page, `changes ${String(width)}`);

      await sheet.getByRole("button", { name: "Принять изменения" }).click();
      await expect(page.getByText("Текст шаблона обновлён")).toBeVisible();
      await expect(sheet).toBeHidden();
    });

    test("без правок: «изменений нет», принять нельзя; плохой файл назван словами", async ({
      page,
    }) => {
      await spaGoto(page, "/admin/templates?tab=documents");
      await pickRowAction(page, "Договор поставки (наш)", "Изменить");
      await upload(page, "SAME");
      const sheet = page.getByRole("dialog", { name: /Что изменилось/ });
      await expect(
        sheet.getByText("Изменений нет: файл совпадает с текстом шаблона."),
      ).toBeVisible();
      await expect(sheet.getByRole("button", { name: "Принять изменения" })).toBeDisabled();
      await sheet.getByRole("button", { name: "Отмена" }).click();
      await expect(sheet).toBeHidden();
      await upload(page, "HOSTILE");
      await expect(page.getByText(/Файл не похож на документ Word/)).toBeVisible();
    });

    test("шаблоны договоров: утверждённый — только скачать; язык файла над таблицей", async ({
      page,
    }) => {
      await spaGoto(page, "/admin/templates?tab=contracts");
      const table = page.getByRole("table", { name: "Шаблоны договоров" });
      await expect(table).toBeVisible();
      await page.locator(".ant-segmented-item-label", { hasText: "UZ" }).click();
      await table.getByRole("button", { name: "Действия: Договор с клиентом · поставка" }).click();
      const items = page.getByRole("menuitem");
      await expect(items.filter({ hasText: "Скачать Word" })).toBeVisible();
      await expect(items.filter({ hasText: "Загрузить из Word" })).toHaveCount(0);
      await page.waitForTimeout(500);
      await screenshot(page, "contracts-menu");
      await expectNoViolations(page, `contracts ${String(width)}`);
    });
  });
}
