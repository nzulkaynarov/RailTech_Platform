import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { confirmDialog, loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { chooseOrAddAddressee } from "./support/fields";

// ДК-5 на MSW, 1512 и 390 px, axe WCAG 2.1 AA: в карточке отправленного заказа партнёру — «Ссылка партнёра в Кабинете»
// (кому ушла, адрес скрыт, открывал ли), снабженец отзывает её после одного подтверждения. Снимки — в E2E_SCREENSHOT_DIR
// (docs/screens/dk5-partners), если он задан. Ширины 1512 и 390: 1512 — ширина ноутбука владельца в этой волне.
const CALC = "ЗВ-2026-097";
const WIDTHS = [1512, 390] as const;
const TITLE = "Ссылка партнёра в Кабинете";
const ORDER = `ЗП-${String(new Date().getFullYear())}-029`;

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
  await expect(page.locator(".ant-message-notice")).toHaveCount(0, { timeout: 15_000 });
  await waitForMotionEnd(page);
  await page.waitForTimeout(400);
  const width = page.viewportSize()?.width ?? 0;
  await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
}

test.describe("ДК-5: ссылка партнёра на заказ", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`снабженец видит ссылку и отзывает её, ${String(width)} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "supply@demo.example");
      await spaGoto(page, `/erp/stock/${encodeURIComponent(ORDER)}`);
      // на телефоне пустое боковое окно «Объект не выбран» ложится поверх карточки — сворачиваем, как в ДК-5 партнёра
      const collapse = page.getByRole("button", { name: /Свернуть/ });
      if (await collapse.isVisible().catch(() => false)) await collapse.click();

      const card = page
        .locator(".ant-card")
        .filter({ has: page.getByRole("heading", { name: TITLE }) });
      await expect(card.getByText("Получатель — d***@steel.example.")).toBeVisible();
      await expect(card.getByText("Партнёр ещё не открывал.")).toBeVisible();
      await card.scrollIntoViewIfNeeded();
      await expectNoViolations(page, `ссылка партнёра ${String(width)}`);
      await shot(page, "dk5-order-partner-link");

      await card.getByRole("button", { name: "Отозвать ссылку" }).click();
      const dialog = page.getByRole("dialog", { name: "Отозвать ссылку на заказ?" });
      await expect(dialog).toBeVisible();
      await expect(
        dialog.getByText(
          "Партнёр по ней больше ничего не увидит. Новая отправка даст новую ссылку.",
        ),
      ).toBeVisible();
      await confirmDialog(page);
      await expect(
        card.getByText("Ссылка отозвана: партнёр по ней ничего не откроет", { exact: false }),
      ).toBeVisible();
      await expect(card.getByRole("button", { name: "Отозвать ссылку" })).toHaveCount(0);
      await card.scrollIntoViewIfNeeded();
      await expectNoViolations(page, `ссылка отозвана ${String(width)}`);
      await shot(page, "dk5-order-partner-link-revoked");
    });
  }
  for (const width of WIDTHS) {
    test(`в журнале запросов цены ссылка партнёра отзывается, ${String(width)} px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "supply@demo.example");
      await spaGoto(page, `/erp/calc/${encodeURIComponent(CALC)}`);
      await page.getByRole("button", { name: "Запросить цену у партнёра" }).click();
      const request = page.getByRole("region", { name: `Запросить цену у партнёра · ${CALC}` });
      await chooseOrAddAddressee(page, "ООО «Вымышленная Сталь»", "Партнёр");
      await request.getByRole("button", { name: "Отправить запрос" }).click();
      await expect(page.getByText("Запрос ушёл на sales@steel.example")).toBeVisible();

      const journal = page.getByRole("list", { name: "Запросы цены у партнёров" });
      const card = journal
        .locator(".ant-card")
        .filter({ has: page.getByRole("heading", { name: TITLE }) });
      await expect(card.getByText("Получатель — d***@steel.example.")).toBeVisible();
      await card.scrollIntoViewIfNeeded();
      await expectNoViolations(page, `ссылка партнёра под запросом ${String(width)}`);
      await shot(page, "dk5-request-partner-link");

      await card.getByRole("button", { name: "Отозвать ссылку" }).click();
      await expect(
        page.getByRole("dialog", { name: "Отозвать ссылку на запрос цены?" }),
      ).toBeVisible();
      await confirmDialog(page);
      await expect(
        card.getByText("Ссылка отозвана: партнёр по ней ничего не откроет", { exact: false }),
      ).toBeVisible();
      await card.scrollIntoViewIfNeeded();
      await expectNoViolations(page, `запрос: ссылка отозвана ${String(width)}`);
      await shot(page, "dk5-request-partner-link-revoked");
    });
  }
});
