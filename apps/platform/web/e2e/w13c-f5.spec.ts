import { appendFileSync } from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// W13C-F5 (малые дефекты гейта C2a, G-5 и G-6) на MSW: редактор договора без обязательных блоков называет недостающие;
// «Что найдёт бот» без ключа эмбеддингов — словами и с подсказкой, куда идти; axe и снимки 1440 и 390 (`E2E_SCREENSHOT_DIR`).
const WIDTHS = [1440, 390] as const;

async function expectNoViolations(page: Page, context: string): Promise<void> {
  await waitForMotionEnd(page);
  // Образец документа — изолированная рамка (`sandbox=""`), axe её не опрашивает (см. admin-company.spec.ts).
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .exclude("iframe.pf-co-frame")
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

test.describe("Мелкие дефекты гейта C2a: G-5 и G-6", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`договор без обязательных блоков: окно называет недостающие, ${String(width)}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/admin/company?tab=templates");
      await page.getByRole("button", { name: "Изменить: Договор поставки (наш)" }).click();
      const editor = page.getByRole("dialog", { name: "Изменить шаблон документа" });
      await editor.getByLabel(/^Текст шаблона/).fill("<p>{{buyer_name}} {{mystery}}</p>");
      await expect(editor.getByText("Неизвестная подстановка {{mystery}}")).toBeVisible();
      await editor.getByRole("button", { name: /Сохранить/ }).click();

      const alert = editor.getByRole("alert");
      await expect(alert).toContainText("В тексте не хватает обязательных блоков документа.");
      await expect(alert).toContainText("Блок: спецификация (Приложение № 1) — {{doc.spec_table}}");
      await expect(alert).toContainText("Блок: итоги и НДС — {{doc.totals}}");
      await expect(alert).toContainText(
        "Блок: реквизиты и подписи Сторон — {{doc.requisites_and_signatures}}",
      );
      // неизвестная подстановка отмечена в списке «Подстановки», раздел раскрыт сам
      await expect(editor.getByText("Нет в списке — в документ попадут как есть")).toBeVisible();
      await expectNoViolations(page, `template missing blocks ${String(width)}`);
      await settledScreenshot(page, "template-missing-blocks");
    });

    test(`поиск базы знаний без ключа эмбеддингов: слова и подсказка, ${String(width)}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/crm/kb");
      await expect(page.getByRole("heading", { level: 1, name: "База знаний" })).toBeVisible();

      await page.getByLabel("Вопрос клиента").fill("поиск без ключа");
      await page.getByRole("button", { name: "Найти" }).click();
      await expect(
        page.getByText(
          "Модель поиска недоступна: добавьте ключ эмбеддингов в Admin · Внешние интеграции, раздел «Модели ИИ», и повторите.",
        ),
      ).toBeVisible();
      await expectNoViolations(page, `kb search without key ${String(width)}`);
      await settledScreenshot(page, "kb-search-no-key");
    });
  }
});
