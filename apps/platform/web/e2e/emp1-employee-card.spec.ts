import { expect, test } from "@playwright/test";

import { expectNoViolations } from "./support/axe";
import { loginAndWait, spaGoto } from "./support/app";
import { measureFit } from "./support/layout";
import { chooseOption } from "./support/fields";

// СОТР-1: карточка сотрудника у администратора — Telegram в трёх состояниях (в списке и в карточке) и замещение за сотрудника
// (назначить, увидеть словами, снять). На MSW; снимки 1512/1440/390 — если задан E2E_SCREENSHOT_DIR; axe на каждой ширине.
const WIDTHS = [1512, 1440, 390] as const;
const PANEL = "#pf-context-panel";
const HEIGHT = 900;

test.describe("Карточка сотрудника: Telegram и замещение", () => {
  for (const width of WIDTHS) {
    test(`администратор видит три состояния Telegram и ставит замещение за сотрудника, ${String(width)} px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: HEIGHT });
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin/org?view=list");
      await expect(page.getByRole("heading", { level: 1, name: "Сотрудники" })).toBeVisible();

      // Список: привязан / не привязан / привязан, но не доходит (на 390 строки — карточки, поэтому поиск по странице)
      await expect(page.getByText("Telegram: нет").first()).toBeVisible();
      await expect(page.getByText("Telegram: не доходит").first()).toBeVisible();
      await expectNoViolations(page, `список, ${String(width)} px`);

      // Карточка сотрудника, у которого сообщения не доходят
      await spaGoto(page, "/admin/org?employee=u-demo-accountant&panel=open");
      const panel = page.locator(PANEL);
      await expect(
        panel.getByRole("heading", { level: 3, name: "Демо Бухгалтеров" }),
      ).toBeVisible();
      await expect(panel.getByText(/сообщения не доходят/)).toBeVisible();

      const shots = process.env["E2E_SCREENSHOT_DIR"];
      if (shots) await page.screenshot({ path: `${shots}/employee-telegram-${String(width)}.png` });

      // Замещение за сотрудника: коллега и период → фраза словами → снять
      const deputy = panel.getByTestId("employee-deputy");
      await expect(deputy.getByText("Замещение не назначено.")).toBeVisible();
      await chooseOption(deputy.getByRole("combobox", { name: "Кто замещает" }), "Демо Директоров");
      const year = new Date().getFullYear() + 1;
      await deputy.getByLabel("С даты").fill(`01.12.${String(year)}`);
      await deputy.getByLabel("С даты").press("Enter");
      await deputy.getByLabel("По дату").fill(`10.12.${String(year)}`);
      await deputy.getByLabel("По дату").press("Enter");
      await deputy.getByRole("button", { name: /Назначить$/ }).click();
      await expect(deputy.getByTestId("employee-deputy-sentence")).toContainText(
        `Демо Директоров с 01.12.${String(year)} по 10.12.${String(year)}`,
      );
      await expectNoViolations(page, `карточка, ${String(width)} px`);
      const dir = process.env["E2E_SCREENSHOT_DIR"];
      if (dir)
        await page.screenshot({
          path: `${dir}/employee-card-${String(width)}.png`,
          fullPage: true,
        });

      await deputy.getByRole("button", { name: /Снять замещение$/ }).click();
      await expect(deputy.getByText("Замещение не назначено.")).toBeVisible();

      // Без горизонтальной прокрутки
      expect((await measureFit(page)).page).toBeLessThanOrEqual(1);
    });
  }
});
