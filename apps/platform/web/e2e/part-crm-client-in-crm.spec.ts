import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// PART-CRM: в блоке «Доступ в кабинет» видно, стал ли приглашённый партнёр клиентом CRM: заведён (со ссылкой на клиента),
// ожидает или конфликт. На MSW. Снимки 1440 и 390 px и axe (WCAG 2.1 AA).

const WIDTHS = [1440, 390] as const;

for (const width of WIDTHS) {
  test(`карточка поставщика: клиент в CRM, ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");

    // Заведён: ссылка ведёт на карточку клиента CRM
    await spaGoto(page, "/erp/catalog?part=suppliers&supplier=2");
    let drawer = page.getByRole("dialog", { name: "АО «Южный Металл»" });
    let block = drawer.getByRole("region", { name: "Доступ в кабинет" });
    await expect(block.getByText("Клиент в CRM")).toBeVisible();
    await expect(block.getByText("Заведён", { exact: true })).toBeVisible();
    await expect(block.getByText("В кабинете: Клиент · Партнёр")).toBeVisible();
    const open = block.getByRole("link", { name: "Открыть клиента CRM №58" });
    await expect(open).toHaveAttribute("href", "/crm/clients/58");
    await expectNoViolations(page, "Поставщик · клиент в CRM заведён");
    await block.scrollIntoViewIfNeeded();
    await settledScreenshot(page, "supplier-crm-client-linked");

    // Конфликт: ничего не изменено, подсказка говорит, что делать
    await spaGoto(page, "/erp/catalog?part=suppliers&supplier=3");
    drawer = page.getByRole("dialog", { name: "ИП «Восточный склад»" });
    block = drawer.getByRole("region", { name: "Доступ в кабинет" });
    await expect(block.getByText("Конфликт", { exact: true })).toBeVisible();
    await expect(block.getByText(/объедините карточки в CRM/)).toBeVisible();
    await expect(block.getByRole("link", { name: "Открыть клиента CRM №88" })).toBeVisible();
    await expectNoViolations(page, "Поставщик · клиент в CRM, конфликт");
    await block.scrollIntoViewIfNeeded();
    await settledScreenshot(page, "supplier-crm-client-conflict");

    // Не приглашён: строки про CRM нет
    await spaGoto(page, "/erp/catalog?part=suppliers&supplier=1");
    drawer = page.getByRole("dialog", { name: "ООО «Поставщик Север»" });
    block = drawer.getByRole("region", { name: "Доступ в кабинет" });
    await expect(block.getByText("Не открыт")).toBeVisible();
    await expect(block.getByText("Клиент в CRM")).toBeHidden();
  });
}
