import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ДП-1: договор поставки без тупика (решение владельца 2026-11-25) на MSW, 1512 (14"), 1440 и 390 px, axe.
// Замечания контрагента (макеты 67–68): комментарий, его редакция, что изменилось, ответы и решение директора при разногласии;
// «Ожидает подписания» → «Отметить: подписан» заметкой (макет 69). Кабинет клиента (макет 67) — снимки dev-сервера Cabinet.
const WIDTHS = [1512, 1440, 390] as const;
const WITH_REMARK = `/eds/projects/${encodeURIComponent("ПР-2026-112")}`;
const WAITING = `/eds/projects/${encodeURIComponent("ПР-2026-106")}`;

for (const width of WIDTHS) {
  test.describe(`${String(width)} px`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize({ width, height: width < 600 ? 844 : 900 });
    });

    test("замечания контрагента: разбор, ответы, решение директора", async ({ page }) => {
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, WITH_REMARK);
      const block = page.getByTestId("contract-remark");
      await expect(block.getByText("Замечания контрагента", { exact: true })).toBeVisible();
      await expect(block.getByTestId("remark-summary")).toContainText("Изменены п. 2.2, 3.1");
      await expect(block.getByText("При разногласии решает: Д. Назаров")).toBeVisible();
      await block.scrollIntoViewIfNeeded();
      await settledScreenshot(page, "dp1-remarks");
      await expectNoViolations(page, "замечания контрагента");

      await block.getByRole("button", { name: "Ответить своей редакцией" }).click();
      await block.getByLabel("Что отвечаем контрагенту").fill("Предоплата 40 %, пеню оставляем.");
      await settledScreenshot(page, "dp1-remarks-counter");
      await block.getByRole("button", { name: "Отправить ответ" }).click();
      await expect(page.getByTestId("contract-remark")).toHaveCount(0);
      const overflow = await page.evaluate<boolean>(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth",
      );
      expect(overflow, "горизонтальной прокрутки нет").toBe(false);
    });

    test("ожидает подписания: «Отметить: подписан» заметкой, срок считается при отметке", async ({
      page,
    }) => {
      await loginAndWait(page, "accountant@demo.example");
      await spaGoto(page, WAITING);
      const sign = page.getByRole("form", { name: "Ожидает подписания" });
      await expect(sign).toBeVisible();
      const submit = sign.getByRole("button", { name: "Отметить: подписан" });
      await expect(submit).toBeDisabled();
      await sign.getByLabel("Или заметка").fill("Подписан в офисе, оригинал у юриста");
      await sign.scrollIntoViewIfNeeded();
      await settledScreenshot(page, "dp1-awaiting-signature");
      await expectNoViolations(page, "ожидает подписания");
      await submit.click();
      await expect(page.getByText("Договор подписан.").first()).toBeVisible();
      await settledScreenshot(page, "dp1-signed");
    });
  });
}
