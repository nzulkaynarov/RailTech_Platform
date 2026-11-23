import { expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, partnerCard } from "./support/app";
import { expectNoViolations } from "./support/axe";

// PART-1: блок «Доступ в кабинет» в карточке партнёра на MSW. Снабженец заводит контакт, выбирает разделы и приглашает;
// статус и роли обновляются на месте; «Приостановить доступ» просит подтверждение. Снимки 1440 и 390 px и axe (WCAG 2.1 AA).

const WIDTHS = [1440, 390] as const;

for (const width of WIDTHS) {
  test(`карточка партнёра: доступ в кабинет, ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/erp/catalog?part=suppliers&supplier=1");
    const drawer = partnerCard(page, "ООО «Поставщик Север»");
    const block = drawer.getByRole("region", { name: "Доступ в кабинет" });
    await expect(block.getByText("Не открыт")).toBeVisible();
    // На телефоне пустое боковое окно ложится поверх листа карточки: сворачиваем его, чтобы лист был виден
    const hidePanel = page.locator("#pf-context-panel .pf-panel-hide");
    if (width === 390 && (await hidePanel.isVisible())) await hidePanel.click();

    // Контакт и приглашение
    await block.getByRole("button", { name: "Добавить контакт" }).click();
    const form = page.getByRole("dialog", { name: "Новый контакт партнёра" });
    await form.getByLabel("ФИО").fill("Нодира Рахимова");
    await form.getByLabel("E-mail").fill("nodira@sever-supply.example");
    await form.getByRole("button", { name: "Добавить" }).click();
    await expect(form).toBeHidden();
    await expect(block.getByText("Нодира Рахимова")).toBeVisible();
    // ДК-5: право подтверждать — одно название в Платформе и Кабинете; раздел покупателя новому партнёру не включён
    await expect(
      block.getByRole("switch", { name: /Может подтверждать: Нодира Рахимова/ }),
    ).toBeChecked();
    await expect(block.getByRole("switch", { name: /Каталог и заявки/ })).not.toBeChecked();
    // ДК-5: контакт, заведённый в карточке, без права подтверждать — приглашающий выбирает право в самом приглашении
    await expect(
      block.getByRole("switch", { name: /Может подтверждать: Азиз Тошматов/ }),
    ).not.toBeChecked();
    await block.getByRole("button", { name: "Пригласить: Азиз Тошматов" }).click();
    const ask = page.getByRole("dialog", { name: "Пригласить в кабинет" });
    await expect(ask.getByRole("switch", { name: "Может подтверждать" })).toBeChecked();
    await ask.getByRole("button", { name: "Пригласить" }).click();
    await expect(ask).toBeHidden();
    await expect(
      block.getByRole("switch", { name: /Может подтверждать: Азиз Тошматов/ }),
    ).toBeChecked();
    await expect(block.getByText("Приглашён", { exact: true })).toBeVisible();
    await expect(block.getByText("В кабинете: Партнёр")).toBeVisible();
    // ДК-5: только продающий партнёр клиентом не становится — CRM ничего не просят (с «Каталог и заявки» — см. part-crm-client-in-crm)
    await expect(block.getByText("Ожидает", { exact: true })).toBeHidden();
    await expectNoViolations(page, `Партнёр · доступ в кабинет`);
    await block
      .getByRole("list", { name: /Контакты/ })
      .evaluate("(el) => { el.scrollIntoView({ block: 'start' }); }");
    await settledScreenshot(page, "supplier-cabinet-access");

    // Приостановка просит подтверждение
    await block.getByRole("button", { name: "Приостановить доступ" }).click();
    const confirm = page.getByRole("dialog", { name: "Приостановить доступ в кабинет" });
    await expectNoViolations(page, `Партнёр · приостановка`);
    await confirm.getByRole("button", { name: "Приостановить" }).click();
    await expect(block.getByText("Приостановлен", { exact: true }).first()).toBeVisible();
    await expect(block.getByText("Кабинет закрыт: партнёр войти не может.")).toBeVisible();
  });
}
