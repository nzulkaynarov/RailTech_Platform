import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ДС-1: срок договора (решение владельца 2026-11-25) на MSW. Карточка договора подписанного проекта: срок, «Продлится
// сам», отказ от продления; настройки «Продажи · Договоры»: правило срока — данные; карточка контрагента: срок и
// предупреждение, когда он вышел. 1512 (14"), 1440 и 390 px, axe.
const WIDTHS = [1512, 1440, 390] as const;
const PROJECT = `/eds/projects/${encodeURIComponent("ПР-2026-097")}`;

for (const width of WIDTHS) {
  test.describe(`${String(width)} px`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize({ width, height: width < 600 ? 844 : 900 });
    });

    test("договор проекта: срок и отказ от продления", async ({ page }) => {
      await loginAndWait(page, "accountant@demo.example");
      await spaGoto(page, PROJECT);
      const term = page.getByTestId("contract-term");
      await expect(term.getByText("Продлится сам")).toBeVisible();
      await expect(term.getByText("Отказаться от продления можно до 01.12.2026.")).toBeVisible();
      await term.scrollIntoViewIfNeeded();
      await settledScreenshot(page, "ds1-contract-term");
      await expectNoViolations(page, "срок договора в проекте");

      await term.getByRole("button", { name: "Отказаться от продления" }).click();
      await page.getByRole("button", { name: "Отказаться от продления" }).last().click();
      await expect(term.getByText("Закончится в срок", { exact: true })).toBeVisible();
      await expect(
        term.getByText("Мы отказались от продления: договор закончится в срок."),
      ).toBeVisible();
      await expect(term.getByRole("button", { name: "Отказаться от продления" })).toHaveCount(0);
      await settledScreenshot(page, "ds1-contract-declined");
      await expectNoViolations(page, "отказ от продления записан");

      // отказ можно вернуть до последнего дня отказа
      await term.getByRole("button", { name: "Вернуть продление" }).click();
      await expect(term.getByText("Продлится сам")).toBeVisible();
    });

    test("настройки «Продажи»: срок договора — правило, а не код", async ({ page }) => {
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/admin/sales");
      const rule = page.getByRole("combobox", { name: "Срок договора по умолчанию" });
      await expect(rule).toBeVisible();
      await expect(page.getByRole("switch", { name: "Договор продлевается сам" })).toBeChecked();
      await expect(
        page.getByRole("spinbutton", { name: "За сколько дней можно отказаться от продления" }),
      ).toHaveValue("30");
      await page
        .getByRole("combobox", { name: "Когда срок договора вышел" })
        .scrollIntoViewIfNeeded();
      await settledScreenshot(page, "ds1-settings-term");
      await expectNoViolations(page, "срок договора в настройках продаж");
      const overflow = await page.evaluate<boolean>(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth",
      );
      expect(overflow, "горизонтальной прокрутки нет").toBe(false);
    });

    test("карточка контрагента: срок вышел — новые КП не создаются", async ({ page }) => {
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/crm/clients/3?panel=open&tab=card");
      await page.getByRole("tab", { name: "Обзор" }).click();
      const term = page.getByTestId("counterparty-term");
      await expect(term.getByText("Срок вышел")).toBeVisible();
      await expect(page.getByText(/Новые КП не создаются, пока договор не продлён/)).toBeVisible();
      await settledScreenshot(page, "ds1-counterparty-expired");
      await expectNoViolations(page, "срок договора в карточке контрагента");
    });
  });
}
