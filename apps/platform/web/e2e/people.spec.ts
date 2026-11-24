import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";
import { expectFitsFrame } from "./support/layout";

const WIDTHS = [1440, 390] as const;

test.describe("Органайзер · Люди", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`открывается и проходит axe на ${String(width)}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/chats/contacts");
      await expect(page.getByRole("heading", { level: 1, name: "Люди" })).toBeVisible();
      await expect(page.locator(".pf-people tbody tr").first()).toBeVisible();
      await expectNoViolations(page, `people ${String(width)}`);
      await settledScreenshot(page, "people");
      if (width !== 390) await expectFitsFrame(page, "people");
    });

    test(`карточка коллеги: контакты скрыты, «Показать контакты» открывает их, ${String(width)}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "accountant@demo.example");
      await spaGoto(page, "/chats/contacts");
      await expect(page.locator(".pf-people tbody tr").first()).toBeVisible();
      // бухгалтер видит коллег: решение 10.11 — имя, должность и роли открыты всем
      await page
        .getByRole("button", { name: "Сотрудники" })
        .or(page.getByText("Сотрудники", { exact: true }))
        .first()
        .click();
      await page.locator(".pf-people-name").first().click();
      const card = page.locator(".pf-people-card");
      await expect(card).toBeVisible();
      await expect(card.getByText("•••").first()).toBeVisible();
      await expectNoViolations(page, `people card ${String(width)}`);
      await settledScreenshot(page, "people-card");
      await card.getByRole("button", { name: "Показать контакты" }).click();
      await expect(card.getByRole("link", { name: /@demo\.example$/ })).toBeVisible();
      await expectNoViolations(page, `people revealed ${String(width)}`);
      await settledScreenshot(page, "people-revealed");
    });
  }

  // PL-1: лид в «Людях» — компания, канал, значки контактов, «Показать контакты» с записью в журнал, «Открыть лид»
  for (const width of [1512, 390]) {
    test(`лид: компания и значки контактов, карточка и «Показать контакты», ${String(width)}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/chats/contacts");
      await page.getByText("Лиды", { exact: true }).first().click();
      const rows = page.locator(".pf-people tbody tr");
      await expect(rows.first()).toBeVisible();
      await expect(page.locator(".pf-people-has").first()).toBeVisible();
      await expectNoViolations(page, `people leads ${String(width)}`);
      await settledScreenshot(page, "people-leads");
      await page
        .getByRole("button", { name: "Показать закрытые" })
        .or(page.getByRole("switch", { name: "Показать закрытые" }))
        .first()
        .click();
      await expectNoViolations(page, `people leads closed ${String(width)}`);
      await page.locator(".pf-people-name").first().click();
      const card = page.locator(".pf-people-card");
      await expect(card).toBeVisible();
      await expect(card.getByRole("button", { name: /^Открыть лид L-/ })).toBeVisible();
      await expectNoViolations(page, `people lead card ${String(width)}`);
      await settledScreenshot(page, "people-lead-card");
      const reveal = card.getByRole("button", { name: "Показать контакты" });
      if (await reveal.count()) {
        await reveal.click();
        await expect(card.getByText("•••")).toHaveCount(0);
        await expectNoViolations(page, `people lead revealed ${String(width)}`);
        await settledScreenshot(page, "people-lead-revealed");
      }
    });
  }
});
