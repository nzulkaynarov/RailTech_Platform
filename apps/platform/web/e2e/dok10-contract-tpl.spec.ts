import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ДОК-10: договор только из утверждённых шаблонов (DECISIONS 2026-11-23), макет — доски 39 и 40 на MSW.
// «Документы · Шаблоны · Договоры»: статус, редакция, кто утвердил; «Новая редакция», «На утверждение», «Утвердить» — юристу.
// Проект: договор по шаблону — метка «По шаблону · без отступлений», путь, «Запросить отступление».
// Настройки «Продажи · Договоры»: авто-отправка, наша подпись, отступления, шаблон по умолчанию. 1440 и 390 px, axe.
const WIDTHS = [1440, 390] as const;
const PROJECT = `/eds/projects/${encodeURIComponent("ПР-2026-104")}`;

for (const width of WIDTHS) {
  test.describe(`${String(width)} px`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize({ width, height: width < 600 ? 844 : 900 });
    });

    test("шаблоны договоров: статус, редакция, утверждение юристом", async ({ page }) => {
      await loginAndWait(page, "lawyer@demo.example");
      await spaGoto(page, "/eds/contract-templates");
      await expect(
        page.getByRole("heading", { level: 1, name: "Шаблоны договоров" }),
      ).toBeVisible();
      const table = page.getByRole("table", { name: "Шаблоны договоров" });
      await expect(table.getByText("ред. 3 от 20.11.2026 · утвердил А. Юсупов")).toBeVisible();
      await expect(table.getByText("в проекте не предлагается")).toBeVisible();
      await settledScreenshot(page, "dok10-templates-list");
      await expectNoViolations(page, "список шаблонов договоров");

      const row = table.getByRole("row", { name: /Договор с клиентом · услуги/ });
      await row.getByRole("button", { name: /Действия/ }).click();
      await page.getByRole("menuitem", { name: "Утвердить" }).click();
      await expect(row.getByText("Утверждён")).toBeVisible();
      await settledScreenshot(page, "dok10-templates-approved");
    });

    test("проект: договор по шаблону, путь и заявка на отступление", async ({ page }) => {
      await page.addInitScript(
        `window.localStorage.setItem("rt-pf-mock-contract-template", "on");`,
      );
      await loginAndWait(page, "accountant@demo.example");
      await spaGoto(page, PROJECT);
      const docs = page.getByRole("region", { name: "Документы проекта" });
      await docs.getByRole("button", { name: "Сформировать проект договора по КП" }).click();
      await expect(docs.getByText("По шаблону · без отступлений")).toBeVisible();
      await expect(docs.getByText("Клиенту уйдёт после нашей подписи.")).toBeVisible();
      await docs.getByRole("list", { name: "Путь договора" }).scrollIntoViewIfNeeded();
      await settledScreenshot(page, "dok10-project-contract");
      await expectNoViolations(page, "договор по шаблону в проекте");

      await docs.getByRole("button", { name: "Запросить отступление" }).click();
      await docs.getByLabel("Пункт и причина").fill("Оплата в течение 30 дней");
      await docs.getByRole("button", { name: "Отправить заявку" }).click();
      await expect(docs.getByText("Отступление ждёт «Право»")).toBeVisible();
      await expect(docs.getByText(/идёт по маршруту виз/)).toBeVisible();
      await docs.getByRole("list", { name: "Путь договора" }).scrollIntoViewIfNeeded();
      await settledScreenshot(page, "dok10-project-deviation");
      await expectNoViolations(page, "отступление ждёт «Право»");
    });

    test("настройки «Продажи»: правила договора — данные", async ({ page }) => {
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/admin/sales");
      await expect(page.getByRole("heading", { level: 2, name: "Договоры" })).toBeVisible();
      // ПК-1: подпись и отправка — под «Дополнительно», на виду срок, продление и шаблоны
      await page.getByRole("button", { name: "Дополнительно" }).click();
      await expect(
        page.getByRole("switch", { name: "Наша подпись — до отправки клиенту" }),
      ).toBeChecked();
      const dir = process.env["E2E_SCREENSHOT_DIR"];
      if (dir) {
        // Страница прокручивается внутри рабочей области: снимаем карточку правил целиком.
        await page
          .locator(".ant-card", { has: page.getByRole("heading", { level: 2, name: "Договоры" }) })
          .screenshot({ path: `${dir}/dok10-sales-rules-${String(width)}.png` });
      }
      await expectNoViolations(page, "правила договора в настройках продаж");
      const overflow = await page.evaluate<boolean>(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth",
      );
      expect(overflow, "горизонтальной прокрутки нет").toBe(false);
    });
  });
}
