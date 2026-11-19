// Сценарий 4. Заказ партнёру → приёмка → отгрузка → поставка → акт.
import { PANEL, Report, as, obs, screen, seen, settle, spaGoto, step } from "./common.mjs";
export const scenarios = {};

// 4a. Снабженец: «Задачи» и колокольчик после принятия КП с дефицитом без поставщика.
scenarios["4a"] = async (browser) => {
  const r = new Report("4a");
  const page = await as(browser, r, "supply");
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  const q = await seen(page, "main", 2500);
  obs(r, "«Задачи» снабженца", { sees: q });
  await page.getByRole("button", { name: /уведомлен/i }).first().click().catch(() => {});
  await page.waitForTimeout(1500);
  obs(r, "колокольчик снабженца", { sees: await seen(page, ".ant-drawer, .ant-popover, [role=dialog]", 1500) });
  await page.keyboard.press("Escape");
  const link = page.getByRole("link", { name: /Открыть/ }).first();
  if (await link.isVisible().catch(() => false)) {
    await link.click();
    await page.waitForTimeout(3000);
    await settle(page);
    obs(r, "экран из строки задачи", { sees: `${page.url()}\n${await seen(page, "main", 2500)}` });
  }
  await page.screenshot({ path: `${process.env.QA_SHOTS}/4a-supply-queue-1440.png` });
  r.save();
};

// 4b. Снабженец: «Контрагенты» → «Добавить партнёра» — форма.
scenarios["4b"] = async (browser) => {
  const r = new Report("4b");
  const page = await as(browser, r, "supply");
  await spaGoto(page, "/crm/clients");
  await settle(page);
  obs(r, "Контрагенты у снабженца", { sees: `${page.url()}\n${await seen(page, "main", 800)}` });
  await step(page, r, "«Добавить партнёра»", async () => {
    await page.getByRole("button", { name: "Добавить партнёра" }).first().click();
    await page.waitForTimeout(2000);
  });
  obs(r, "форма партнёра", { sees: `${page.url()}\n${await seen(page, PANEL, 2000)}\nполя: ${(await page.locator(PANEL).locator("label").allInnerTexts()).join(" | ")}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/4b-partner-form-1440.png` });
  r.save();
};

// 4c. Снабженец: партнёр «ООО Демо Сталь» (Узбекистан, сум, ИНН) с контактом → «Добавить».
scenarios["4c"] = async (browser) => {
  const r = new Report("4c");
  const page = await as(browser, r, "supply");
  await spaGoto(page, "/crm/clients?partner=new&panel=open&tab=card");
  await settle(page);
  const panel = page.locator(PANEL);
  const pick = async (label, text) => {
    await panel.getByLabel(label).click();
    await page.waitForTimeout(600);
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option", { hasText: text }).first().click();
  };
  await step(page, r, "компания партнёра", async () => {
    await panel.getByLabel("Название").fill("ООО Демо Сталь");
    await pick("Страна", "Узбекистан").catch(async () => obs(r, "страна", { sees: "выбор страны не сработал" }));
    await pick("Валюта цен", /UZS|сум/).catch(async () => obs(r, "валюта", { sees: "выбор валюты не сработал" }));
    await panel.getByLabel("ИНН").fill("302345678");
    await panel.getByRole("button", { name: "Далее: Контакт" }).click();
    await page.waitForTimeout(800);
  });
  await step(page, r, "контакт партнёра", async () => {
    await panel.getByLabel("Контактное лицо").fill("Бахтиёр Сталев");
    await panel.getByLabel("Почта").fill("partner.sc2@demo.example");
    await panel.getByLabel("Телефон").fill("+998901234500");
  });
  await step(page, r, "«Добавить»", async () => {
    await panel.getByRole("button", { name: "Добавить", exact: true }).click();
    await page.waitForTimeout(4000);
    await settle(page);
  });
  obs(r, "после добавления партнёра", { sees: `${page.url()}\n${await seen(page, PANEL, 1800)}` });
  const err = await seen(page, ".ant-message, .ant-notification, [role=alert]", 500);
  if (err) obs(r, "сообщение", { sees: err });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/4c-partner-added-1440.png` });
  r.save();
};

// 4d. Снабженец: «Склад» → «Создать заказ» → «На дефицит заявки» — что предлагает форма.
scenarios["4d"] = async (browser) => {
  const r = new Report("4d");
  const page = await as(browser, r, "supply");
  await spaGoto(page, "/erp/stock");
  await settle(page);
  obs(r, "Склад", { sees: `${page.url()}\n${await seen(page, "main", 1500)}` });
  await step(page, r, "«Создать заказ»", async () => {
    await page.getByRole("button", { name: /Создать заказ|Новый заказ/ }).first().click();
    await page.waitForTimeout(2000);
  });
  await step(page, r, "«На дефицит заявки»", async () => {
    await page.getByText("На дефицит заявки", { exact: true }).first().click();
    await page.waitForTimeout(2000);
  });
  obs(r, "форма заказа на дефицит", { sees: `${page.url()}\n${await seen(page, PANEL, 2500)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/4d-order-shortage-1440.png` });
  r.save();
};
