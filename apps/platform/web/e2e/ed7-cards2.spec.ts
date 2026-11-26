import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ЕД-7 PR-2: счёт, согласование, КП и входящее письмо — «одно место для каждого сведения»: форма решения в центре, вкладки
// окна «Сведения» · «Маршрут» · «Обсуждение» · «История»; снимки 1440 и 390 (окно открыто) и axe.
const WIDTHS = [1440, 390];

for (const width of WIDTHS) {
  test.describe(`ЕД-7: карточки решений, ${String(width)} px`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    });

    test("счёт: форма оплаты в центре, «Сведения» и «История» в окне", async ({ page }) => {
      await loginAndWait(page, "accountant@demo.example");
      await spaGoto(
        page,
        `/eds/payments/${encodeURIComponent("СЧ-2026/147")}?panel=open&tab=history`,
      );
      await expect(page.getByRole("heading", { level: 1, name: "СЧ-2026/147" })).toBeVisible();
      await expect(page.getByRole("list", { name: "Журнал счёта" })).toBeVisible();
      await settledScreenshot(page, "invoice-history-panel");
      await expectNoViolations(page, `счёт, окно «История» ${String(width)}`);

      await spaGoto(page, `/eds/payments/${encodeURIComponent("СЧ-2026/142")}`);
      await expect(page.getByRole("heading", { level: 1, name: "СЧ-2026/142" })).toBeVisible();
      const form = page
        .locator(".pf-dec-center")
        .getByRole("form", { name: "Подтверждение оплаты" });
      await form.scrollIntoViewIfNeeded();
      await expect(form).toBeVisible();
      await settledScreenshot(page, "invoice-decision-center");
      await expectNoViolations(page, `счёт, форма в центре ${String(width)}`);
    });

    test("согласование: форма в центре, «Маршрут» — одна лента", async ({ page }) => {
      await loginAndWait(page, "director@demo.example");
      await spaGoto(
        page,
        `/eds/approvals/${encodeURIComponent("СЗ-2026/014")}?panel=open&tab=route`,
      );
      await expect(page.getByRole("heading", { level: 1, name: "СЗ-2026/014" })).toBeVisible();
      await expect(page.getByRole("list", { name: "Маршрут согласования" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Решения" })).toHaveCount(0);
      await settledScreenshot(page, "approval-route-panel");
      await expectNoViolations(page, `согласование, «Маршрут» ${String(width)}`);

      await spaGoto(page, `/eds/approvals/${encodeURIComponent("СЗ-2026/014")}`);
      const form = page
        .locator(".pf-dec-center")
        .getByRole("form", { name: "Согласование документа" });
      await form.scrollIntoViewIfNeeded();
      await expect(form).toBeVisible();
      await settledScreenshot(page, "approval-decision-center");
      await expectNoViolations(page, `согласование, форма в центре ${String(width)}`);
    });

    test("КП: «Сведения», «Маршрут», «Обсуждение»; форма одобрения в центре", async ({ page }) => {
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, `/eds/drafts/${encodeURIComponent("КП-2026/113")}?panel=open&tab=chat`);
      await expect(page.getByRole("heading", { level: 1, name: "КП-2026/113" })).toBeVisible();
      await expect(page.getByRole("list", { name: "Комментарии клиента к КП" })).toBeVisible();
      await settledScreenshot(page, "quote-chat-panel");
      await expectNoViolations(page, `КП, «Обсуждение» ${String(width)}`);

      await spaGoto(page, `/eds/drafts/${encodeURIComponent("КП-2026/115")}?panel=open&tab=facts`);
      await expect(page.getByRole("heading", { level: 1, name: "КП-2026/115" })).toBeVisible();
      await settledScreenshot(page, "quote-facts-panel");
      await expectNoViolations(page, `КП, «Сведения» ${String(width)}`);

      await spaGoto(page, `/eds/drafts/${encodeURIComponent("КП-2026/115")}`);
      const form = page.locator(".pf-dec-center").getByRole("form", { name: "Одобрение КП" });
      await form.scrollIntoViewIfNeeded();
      await expect(form).toBeVisible();
      await settledScreenshot(page, "quote-decision-center");
      await expectNoViolations(page, `КП, форма в центре ${String(width)}`);
    });

    test("входящее письмо: «Сведения» и «История», форма резолюции в центре", async ({ page }) => {
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/eds/inbox/%D0%92%D0%A5-104%2F26?panel=open&tab=facts");
      await expect(page.getByRole("heading", { level: 1, name: "Письмо ВХ-104/26" })).toBeVisible();
      await expect(page.getByText("Зарегистрировано", { exact: true })).toBeVisible();
      await settledScreenshot(page, "letter-facts-panel");
      await expectNoViolations(page, `письмо, «Сведения» ${String(width)}`);

      await spaGoto(page, "/eds/inbox/%D0%92%D0%A5-104%2F26");
      const form = page.locator(".pf-dec-center").getByRole("form", { name: "Резолюция" });
      await form.scrollIntoViewIfNeeded();
      await expect(form).toBeVisible();
      await settledScreenshot(page, "letter-decision-center");
      await expectNoViolations(page, `письмо, форма в центре ${String(width)}`);
    });
  });
}
