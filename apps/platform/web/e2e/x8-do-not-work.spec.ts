import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// Х-8 на MSW: «Не работать» у контрагента — причина обязательна, полоса «С компанией не работаем» в карточках контрагента и
// проекта, пометка и фильтр «Не работаем» в списке, «Снова работать» снимает. Снимки 1440 и 390 с axe.
const dir = process.env["E2E_SCREENSHOT_DIR"];
const REASON = "Дважды не оплатил отгруженный заказ";

for (const width of [1440, 390] as const) {
  test(
    `«Не работать»: отметка, полоса, список, проект, снятие, ${String(width)}`,
    {
      tag: "@mobile",
    },
    async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "supply@demo.example");

      // 1. карточка поставщика; название — как у клиента проекта ПР-2026-105, чтобы увидеть полосу и там
      await spaGoto(page, "/crm/clients?partner=1&panel=open&tab=card");
      await page.getByRole("button", { name: "Реквизиты" }).click();
      const requisites = page.getByRole("dialog", { name: "Реквизиты контрагента" });
      await requisites.getByLabel("Название").fill("АО «Демо-Транс»");
      await requisites.getByRole("button", { name: "Сохранить" }).click();
      await expect(requisites).toBeHidden();
      await expect(page.getByRole("heading", { name: "АО «Демо-Транс»", level: 3 })).toBeVisible();

      // 2. «Не работать»: без причины кнопка закрыта
      await page.getByRole("button", { name: "Не работать" }).click();
      const dialog = page.getByRole("dialog", { name: "С компанией не работаем" });
      await expect(dialog.getByRole("button", { name: "Отметить" })).toBeDisabled();
      await dialog.getByLabel("Причина").fill(REASON);
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/dialog-${String(width)}.png` });
      await expectNoViolations(page, "«Не работать»: окно причины");
      await dialog.getByRole("button", { name: "Отметить" }).click();
      await expect(dialog).toBeHidden();

      // 3. полоса в карточке контрагента
      const strip = page.locator(".pf-dnw");
      await expect(strip).toContainText(`С компанией не работаем: ${REASON}`);
      await expect(page.getByRole("button", { name: "Снова работать" })).toBeVisible();
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/card-${String(width)}.png`, fullPage: true });
      await expectNoViolations(page, "«Не работать»: карточка контрагента");

      // 4. список: пометка и фильтр «Не работаем» (список поставщиков моков держит прежнее название — реквизиты правят карточку)
      await spaGoto(page, "/crm/clients?kind=do_not_work");
      await expect(
        page.getByRole("link", { name: /Открыть карточку .*Поставщик Север/ }),
      ).toBeVisible();
      await waitForMotionEnd(page);
      if (dir) await page.screenshot({ path: `${dir}/list-${String(width)}.png`, fullPage: true });
      await expectNoViolations(page, "«Не работать»: список, фильтр «Не работаем»");

      // 5. карточка проекта этой компании: документы на месте, сверху полоса
      await spaGoto(page, `/eds/projects/${encodeURIComponent("ПР-2026-105")}`);
      await expect(page.locator(".pf-dnw")).toContainText(`С компанией не работаем: ${REASON}`);
      await expect(page.getByRole("region", { name: "Документы проекта" })).toBeVisible();
      await waitForMotionEnd(page);
      if (dir)
        await page.screenshot({ path: `${dir}/project-${String(width)}.png`, fullPage: true });
      await expectNoViolations(page, "«Не работать»: карточка проекта");

      // 6. «Снова работать» снимает отметку
      await spaGoto(page, "/crm/clients?partner=1&panel=open&tab=card");
      await page.getByRole("button", { name: "Снова работать" }).click();
      await expect(page.locator(".pf-dnw")).toBeHidden();
      await expect(page.getByRole("button", { name: "Не работать" })).toBeVisible();
    },
  );
}
