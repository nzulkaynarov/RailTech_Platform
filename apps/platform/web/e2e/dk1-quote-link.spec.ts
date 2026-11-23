import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

import { confirmDialog, loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";

// ДК-1 на MSW, 1440 и 390 px, axe WCAG 2.1 AA: в карточке отправленного КП — «Ссылка клиента в Кабинете»: срок, получатель
// (адрес замаскирован), открывал ли клиент; тот, кто отправляет КП, отзывает ссылку (одно подтверждение), после отзыва кнопки нет.
// Снимки — в E2E_SCREENSHOT_DIR (docs/screens/dk12-doc-link), если он задан.
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

async function shot(page: Page, name: string): Promise<void> {
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (!dir) return;
  await waitForMotionEnd(page);
  await page.waitForTimeout(400);
  const width = page.viewportSize()?.width ?? 0;
  await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
}

async function scrollTo(target: Locator): Promise<void> {
  await expect(async () => {
    await target.scrollIntoViewIfNeeded({ timeout: 2000 });
  }).toPass({ timeout: 10_000 });
}

const quotePath = (number: string, query = "") =>
  `/eds/drafts/${encodeURIComponent(number)}${query}`;

test.describe("ДК-1: ссылка клиента на КП и отзыв", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`менеджер видит ссылку и отзывает её, ${String(width)} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, quotePath("КП-2026/113", "?panel=closed"));

      const card = page
        .locator(".ant-card")
        .filter({ has: page.getByRole("heading", { name: "Ссылка клиента в Кабинете" }) });
      await expect(card.getByText("Ссылка действует до 27.12.2026.")).toBeVisible();
      await expect(card.getByText("Получатель — a***@demo-put.example.")).toBeVisible();
      await expect(card.getByText(/Клиент открывал: /)).toBeVisible();
      await scrollTo(card);
      await expectNoViolations(page, `ссылка клиента ${String(width)}`);
      await shot(page, "dk1-link-active");

      await card.getByRole("button", { name: "Отозвать ссылку" }).click();
      const dialog = page.getByRole("dialog", { name: "Отозвать ссылку на КП?" });
      await expect(dialog).toBeVisible();
      await expect(
        dialog.getByText(
          "Клиент по ней больше ничего не увидит. Новая отправка КП даст новую ссылку.",
        ),
      ).toBeVisible();
      await expectNoViolations(page, `подтверждение отзыва ${String(width)}`);
      await shot(page, "dk1-link-revoke-confirm");
      await confirmDialog(page);

      await expect(
        card.getByText("Ссылка отозвана: клиент по ней ничего не откроет", { exact: false }),
      ).toBeVisible();
      await expect(card.getByRole("button", { name: "Отозвать ссылку" })).toHaveCount(0);
      await scrollTo(card);
      await expectNoViolations(page, `после отзыва ${String(width)}`);
      await shot(page, "dk1-link-revoked");
    });
  }
});
