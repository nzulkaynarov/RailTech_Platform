import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, waitForMotionEnd } from "./support/app";

// ДВ-5 на MSW: Настройки · Оферта и политика — карточки документов, чтение на трёх языках, правка черновика, публикация с
// подтверждением, журнал принятий. axe 0 и снимки 1440 и 390 (`E2E_SCREENSHOT_DIR`).
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
    const overflow = await page.evaluate<number>(
      "document.documentElement.scrollWidth - document.documentElement.clientWidth",
    );
    expect(overflow, `${name} ${String(width)}: горизонтальная прокрутка`).toBeLessThanOrEqual(0);
    await settledScreenshot(page, name);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

test.describe("Оферта и политика", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("директор читает, правит черновик, публикует и видит журнал принятий", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await page.goto("/admin/legal");
    await expect(page.getByRole("heading", { level: 1, name: "Оферта и политика" })).toBeVisible();
    await expect(page.getByText("Приняли: 3")).toBeVisible();
    await expect(page.getByRole("table", { name: "Журнал принятий" })).toBeVisible();
    await shoot(page, "legal-settings");

    // чтение на узбекском: тот же текст, реквизиты подставлены
    await page.getByRole("button", { name: "Читать" }).first().click();
    await expect(page.getByText("Так текст увидит контакт")).toBeVisible();
    await page.getByText("Özbekça", { exact: true }).click();
    await expect(page.getByText(/Operator ООО «РейлТех Демо»/).first()).toBeVisible();
    await shoot(page, "legal-reader-uz");
    await page.getByRole("button", { name: "К списку" }).click();

    // правка черновика условий
    await page.getByRole("button", { name: "Править черновик" }).click();
    await expect(page.getByRole("textbox", { name: "Название документа" })).toBeVisible();
    await page
      .getByRole("textbox", { name: "Название документа" })
      .fill("Условия использования Кабинета (оферта), ред. 2");
    await shoot(page, "legal-editor");
    await page.getByRole("button", { name: "Сохранить черновик" }).click();
    await expect(page.getByText("Черновик сохранён.")).toBeVisible();

    // публикация: подтверждение называет последствие
    await page.getByRole("button", { name: "Опубликовать" }).click();
    const dialog = page.getByRole("dialog", { name: /Опубликовать редакцию/ });
    await expect(dialog).toContainText(
      "Все контакты кабинета примут новую редакцию при следующем входе",
    );
    await shoot(page, "legal-publish-confirm");
    await dialog.getByRole("button", { name: "Опубликовать" }).click();
    await expect(page.getByText(/опубликована\.$/)).toBeVisible();
    await expect(page.getByText("Не опубликована")).toHaveCount(0);
    await shoot(page, "legal-published");
  });
});
