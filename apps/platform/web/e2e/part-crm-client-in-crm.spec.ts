import { expect, test, type Page } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, partnerCard } from "./support/app";
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
    let drawer = partnerCard(page, "АО «Южный Металл»");
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
    drawer = partnerCard(page, "ИП «Восточный склад»");
    block = drawer.getByRole("region", { name: "Доступ в кабинет" });
    await expect(block.getByText("Конфликт", { exact: true })).toBeVisible();
    await expect(block.getByText(/Проверьте ИНН/)).toBeVisible();
    await expect(block.getByRole("link", { name: "Открыть клиента CRM №88" })).toBeVisible();
    await expectNoViolations(page, "Поставщик · клиент в CRM, конфликт");
    await block.scrollIntoViewIfNeeded();
    await settledScreenshot(page, "supplier-crm-client-conflict");

    // Не приглашён: строки про CRM нет
    await spaGoto(page, "/erp/catalog?part=suppliers&supplier=1");
    drawer = partnerCard(page, "ООО «Поставщик Север»");
    block = drawer.getByRole("region", { name: "Доступ в кабинет" });
    await expect(block.getByText("Не открыт")).toBeVisible();
    await expect(block.getByText("Клиент в CRM")).toBeHidden();
  });
}

// Карточка клиента CRM: партнёр ERP, совпавший по ИНН, ждёт решения менеджера (подтвердить или завести нового клиента).
for (const width of WIDTHS) {
  test(`карточка клиента: партнёр ждёт подтверждения, ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/crm/clients/6?panel=open&tab=card");
    const partner = page.getByRole("region", { name: "Партнёр из кабинета ждёт подтверждения" });
    await expect(partner.getByText("Демо Мануфактуринг ООО")).toBeVisible();
    await expect(partner.getByText(/совпал ИНН/)).toBeVisible();
    await expect(partner.getByRole("button", { name: "Это та же компания" })).toBeVisible();
    await expectNoViolations(page, "Клиент · партнёр ждёт подтверждения");
    await partner.scrollIntoViewIfNeeded();
    await settledScreenshot(page, "client-partner-confirmation");
    await partner.getByRole("button", { name: "Это та же компания" }).click();
    await expect(partner).toBeHidden();
  });
}

// «Удержано» (передача клиента по ИНН нашла компанию партнёра) и «Найден клиент CRM по ИНН: это та же компания?» с ответами
// «Да» и «Нет». Состояние блока ставит служебный запрос мока (в боевой цепочке его создают события ERP и CRM).
async function stage(page: Page, supplier: number, crm: Record<string, unknown>) {
  await page.evaluate(
    async ([id, body]) => {
      await fetch(`/api/v1/__mock/supplier-access/${String(id)}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
    },
    [supplier, crm] as const,
  );
}

for (const width of WIDTHS) {
  test(`карточка поставщика: удержано и непроверенное сопоставление, ${String(width)} px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    // Состояния ставятся до первого открытия карточки: данные карточки кэшируются.
    await stage(page, 2, { status: "held", crm_client_id: "4001" });
    await stage(page, 3, {
      status: "unverified",
      crm_client_id: "4001",
      crm_client_name: "ООО Чужой Клиент",
      inn: "300000999",
    });
    await spaGoto(page, "/erp/catalog?part=suppliers&supplier=2");
    let block = page.getByRole("region", { name: "Доступ в кабинет" });
    await expect(block.getByText("Удержано до сверки", { exact: true })).toBeVisible();
    await expect(block.getByText(/Удержано после передачи клиента/)).toBeVisible();
    await expectNoViolations(page, "Поставщик · удержано до сверки");
    await block.scrollIntoViewIfNeeded();
    await settledScreenshot(page, "supplier-crm-client-held");

    await spaGoto(page, "/erp/catalog?part=suppliers&supplier=3");
    block = page.getByRole("region", { name: "Доступ в кабинет" });
    await expect(
      block.getByText(/Найден клиент CRM «ООО Чужой Клиент», ИНН 300000999/),
    ).toBeVisible();
    await expect(block.getByText(/Это та же компания\?/)).toBeVisible();
    await expectNoViolations(page, "Поставщик · непроверенное сопоставление");
    await block.scrollIntoViewIfNeeded();
    await settledScreenshot(page, "supplier-crm-client-unverified");

    await block.getByRole("button", { name: "Да, та же компания" }).click();
    await expect(block.getByText("Заведён", { exact: true })).toBeVisible();
    await expect(block.getByRole("button", { name: "Да, та же компания" })).toBeHidden();
  });
}

test("карточка поставщика: «Нет, другая компания» снимает сопоставление и запрашивает клиента заново", async ({
  page,
}) => {
  await loginAndWait(page, "supply@demo.example");
  await stage(page, 1, {
    status: "unverified",
    crm_client_id: "4002",
    crm_client_name: "ООО Чужой Клиент",
    inn: "300000777",
  });
  await spaGoto(page, "/erp/catalog?part=suppliers&supplier=1");
  const block = page.getByRole("region", { name: "Доступ в кабинет" });
  await block.getByRole("button", { name: "Нет, другая компания" }).click();
  await expect(block.getByText("Ожидает", { exact: true })).toBeVisible();
  await expect(block.getByRole("button", { name: "Нет, другая компания" })).toBeHidden();
});
