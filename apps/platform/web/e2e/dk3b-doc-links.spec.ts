import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

import { confirmDialog, loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";

// ДК-3б на MSW, 1440 и 390 px, axe WCAG 2.1 AA: в карточке проекта ПР-2026-097 у договора, счёта и акта — «Ссылка клиента
// в Кабинете» (получатели с замаскированным адресом, открывали ли); бухгалтер отзывает ссылку одного документа после
// одного подтверждения, ссылки других документов остаются; менеджер блока не видит. Снимки — в E2E_SCREENSHOT_DIR
// (docs/screens/dk3b-revoke), если он задан.
const WIDTHS = [1440, 390] as const;
const TITLE = "Ссылка клиента в Кабинете";

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

async function scrollTo(target: Locator): Promise<void> {
  await expect(async () => {
    await target.scrollIntoViewIfNeeded({ timeout: 2000 });
  }).toPass({ timeout: 10_000 });
}

const card = (page: Page, index: number): Locator =>
  page
    .locator(".ant-card")
    .filter({ has: page.getByRole("heading", { name: TITLE }) })
    .nth(index);

test.describe("ДК-3б: ссылка клиента на договор, счёт и акт", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`бухгалтер видит три ссылки и отзывает ссылку счёта, ${String(width)} px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "accountant@demo.example");
      await spaGoto(page, `/eds/projects/${encodeURIComponent("ПР-2026-097")}`);

      await expect(page.getByRole("heading", { name: TITLE })).toHaveCount(3);
      const [contract, invoice, act] = [card(page, 0), card(page, 1), card(page, 2)] as const;
      await expect(contract.getByText("Получатель — d***@demo-signal.example.")).toBeVisible();
      await expect(contract.getByText("Получатель — b***@demo-signal.example.")).toBeVisible();
      await expect(invoice.getByText("Клиент ещё не открывал.")).toBeVisible();
      await expect(act.getByText(/Клиент открывал: /)).toBeVisible();
      await scrollTo(contract);
      await expectNoViolations(page, `ссылки документов ${String(width)}`);
      await shot(page, "dk3b-contract-links");
      await scrollTo(invoice);
      await shot(page, "dk3b-invoice-link");
      await scrollTo(act);
      await shot(page, "dk3b-act-link");

      await invoice.getByRole("button", { name: "Отозвать ссылку" }).click();
      const dialog = page.getByRole("dialog", { name: "Отозвать ссылку на счёт?" });
      await expect(dialog).toBeVisible();
      await expect(
        dialog.getByText(
          "Клиент по ней больше ничего не увидит. Новая отправка документа даст новую ссылку.",
        ),
      ).toBeVisible();
      await expectNoViolations(page, `подтверждение отзыва ${String(width)}`);
      await shot(page, "dk3b-revoke-confirm");
      await confirmDialog(page);

      await expect(
        invoice.getByText("Ссылка отозвана: клиент по ней ничего не откроет", { exact: false }),
      ).toBeVisible();
      await expect(invoice.getByRole("button", { name: "Отозвать ссылку" })).toHaveCount(0);
      // ссылки договора и акта живы
      await expect(contract.getByRole("button", { name: "Отозвать ссылку" })).toBeVisible();
      await expect(act.getByRole("button", { name: "Отозвать ссылку" })).toBeVisible();
      await scrollTo(invoice);
      await expectNoViolations(page, `после отзыва ${String(width)}`);
      await shot(page, "dk3b-invoice-revoked");
    });
  }

  test("менеджер без права отправлять документы блока не видит", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, `/eds/projects/${encodeURIComponent("ПР-2026-097")}`);
    await expect(page.getByText("ДОГ-2026/097")).toBeVisible();
    await expect(page.getByRole("heading", { name: TITLE })).toHaveCount(0);
  });
});
