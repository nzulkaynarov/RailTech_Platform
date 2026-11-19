// Сценарий 7. Служебная записка: написать → согласовать → оплатить → автор видит итог.
import { PANEL, Report, as, obs, seen, settle, spaGoto, step } from "./common.mjs";
export const scenarios = {};

/** Видимые кнопки области. */
async function buttonsOf(page, selector = "body") {
  return page.locator(`${selector} button:visible, ${selector} a[role=button]:visible, ${selector} a.ant-btn:visible`).evaluateAll((els) =>
    [...new Set(els.map((e) => `${e.innerText.trim().replace(/\s+/g, " ")}${e.disabled ? " [disabled]" : ""}`).filter(Boolean))],
  );
}

// 7a. Снабженец: «Создать → Служебная записка» на оплату доставки по проекту, сумма, срок, счёт → «Отправить на согласование».
scenarios["7a"] = async (browser) => {
  const r = new Report("7a");
  const page = await as(browser, r, "supply");
  await settle(page);
  await step(page, r, "«Создать → Служебная записка»", async () => {
    await page.getByRole("button", { name: "Создать" }).first().click();
    await page.waitForTimeout(800);
    await page.getByText("Внутренний документ", { exact: true }).first().click();
    await page.waitForTimeout(2500);
    await settle(page);
  });
  const main = page.locator("main");
  obs(r, "форма", { sees: `${page.url()}\n${await seen(page, "main", 2500)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/7a-form-1440.png` });
  await step(page, r, "о чём: тема, сумма, срок, проект", async () => {
    await main.getByLabel("Тема", { exact: true }).fill("Оплата доставки материалов по проекту PRJ-2026-001");
    await main.getByLabel(/^Сумма/).fill("1500000");
    const due = main.getByLabel("Нужно до");
    await due.click();
    await page.keyboard.type("25.11.2026");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(500);
    const deal = main.getByLabel("Связь с проектом");
    if (await deal.isVisible().catch(() => false)) {
      await deal.click({ force: true });
      await page.keyboard.type("PRJ-2026");
      await page.waitForTimeout(2000);
      const opts = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option");
      obs(r, "подсказки «Связь с проектом»", { sees: (await opts.allInnerTexts()).join(" | ") || "пусто" });
      await opts.first().click().catch(() => {});
    }
  });
  const next = async () => {
    const b = main.getByRole("button", { name: /^Далее/ }).first();
    if (!(await b.isVisible().catch(() => false))) return false;
    const name = (await b.innerText()).trim();
    await b.click();
    await page.waitForTimeout(1500);
    const e = (await page.locator(".ant-form-item-explain-error:visible").allInnerTexts()).join(" | ");
    obs(r, `«${name}»`, { sees: e ? `ошибки: ${e}` : "" });
    return true;
  };
  await next();
  await step(page, r, "текст и счёт", async () => {
    const editor = main.locator("[contenteditable=true]").first();
    const area = main.getByLabel("Текст", { exact: true });
    const body = "Прошу оплатить доставку материалов на объект клиента по проекту PRJ-2026-001: 1 500 000 сум по счёту ООО «Быстрая доставка» № 77 от 19.11.2026. Счёт приложен.";
    if (await editor.isVisible().catch(() => false)) { await editor.click(); await page.keyboard.type(body); }
    else await area.fill(body);
    await main.locator('input[type="file"]').first().setInputFiles(process.env.SC2_COURIER);
    await page.waitForTimeout(3000);
  });
  await next();
  obs(r, "шаг «Согласование»", { sees: (await seen(page, "main", 5000)).split("Согласование")[1]?.slice(0, 700) ?? "" });
  await next();
  obs(r, "шаг «Проверка и отправка»", { sees: (await seen(page, "main", 6000)).split("Проверка и отправка")[1]?.slice(0, 900) ?? "" });
  obs(r, "кнопки", { sees: (await buttonsOf(page, "main")).join(" | ") });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/7a-check-1440.png` });
  await step(page, r, "«Отправить на согласование»", async () => {
    await main.getByRole("button", { name: "Отправить на согласование" }).click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) { obs(r, "окно", { sees: await seen(page, '[role="dialog"]', 600) }); await dlg.getByRole("button").last().click(); }
    await page.waitForTimeout(3500);
    await settle(page);
  });
  const e = (await page.locator(".ant-form-item-explain-error:visible, .ant-message:visible, [role=alert]:visible").allInnerTexts()).join(" | ");
  if (e) obs(r, "сообщения", { sees: e });
  obs(r, "после отправки", { sees: `${page.url()}\n${(await seen(page, PANEL, 1500)) || (await seen(page, "main", 1500))}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/7a-after-1440.png` });
  r.save();
};

// 7p. Снабженец: что в меню «Создать» и в левом меню (поиск входа в служебную записку).
scenarios["7p"] = async (browser) => {
  const r = new Report("7p");
  const page = await as(browser, r, "supply");
  await settle(page);
  obs(r, "левое меню", { sees: (await page.locator("nav, aside").first().innerText().catch(() => "")).replace(/\n/g, " | ") });
  await page.getByRole("button", { name: "Создать" }).first().click();
  await page.waitForTimeout(1200);
  obs(r, "после «Создать»", { sees: (await page.locator(".ant-popover:visible, .ant-dropdown:visible, [role=menu]:visible, [role=dialog]:visible, .ant-drawer:visible").allInnerTexts()).join(" || ").replace(/\n/g, " | ") });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/7p-create-1440.png` });
  await page.keyboard.press("Escape");
  await spaGoto(page, "/eds/new?type=memo");
  await settle(page);
  obs(r, "/eds/new?type=memo напрямую", { sees: `${page.url()}\n${await seen(page, "main", 1200)}` });
  r.save();
};

/** «Главная» роли → строка задачи с текстом → «Открыть». */
async function openTask(page, r, text) {
  obs(r, "«Главная»", { sees: `${page.url()}\n${await seen(page, "main", 1600)}` });
  const row = page.locator("main li, main [role=listitem], main .ant-list-item, main tr").filter({ hasText: text }).last();
  obs(r, "строка задачи", { sees: (await row.innerText().catch(() => "нет")).replace(/\n/g, " · ") });
  const open = row.getByRole("button").or(row.getByRole("link")).first();
  if (await open.isVisible().catch(() => false)) {
    await step(page, r, "«Открыть»", async () => { await open.click(); await page.waitForTimeout(2500); await settle(page); });
    return true;
  }
  return false;
}

// 7b. Директор: задача по служебке → карточка → «Согласовать».
scenarios["7b"] = async (browser) => {
  const r = new Report("7b");
  const page = await as(browser, r, "director");
  await settle(page);
  if (!(await openTask(page, r, /MEMO-2026\/001|Оплата доставки/))) {
    await spaGoto(page, "/eds/documents?box=internal&scope=all&doc=5e3d3229-560e-4406-92ec-3c85319b72b6&panel=open");
    await settle(page);
  }
  obs(r, "карточка", { sees: `${page.url()}\n${(await seen(page, PANEL, 2500)) || (await seen(page, "main", 2500))}` });
  obs(r, "кнопки", { sees: (await buttonsOf(page, "body")).join(" | ") });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/7b-card-1440.png` });
  await step(page, r, "«Согласовать»", async () => {
    await page.getByRole("button", { name: "Согласовать", exact: true }).first().click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) { obs(r, "окно", { sees: await seen(page, '[role="dialog"]', 600) }); await dlg.getByRole("button").last().click(); }
    await page.waitForTimeout(3500);
    await settle(page);
  });
  const e = (await page.locator(".ant-message:visible, [role=alert]:visible").allInnerTexts()).join(" | ");
  if (e) obs(r, "сообщения", { sees: e });
  obs(r, "после решения", { sees: `${page.url()}\n${(await seen(page, PANEL, 1500)) || (await seen(page, "main", 1500))}` });
  r.save();
};

// 7c. Бухгалтер: задача по служебке → «Оплатить в «Финансы»» → форма оплаты: дата, сумма, платёжка → «Оплачено».
scenarios["7c"] = async (browser) => {
  const r = new Report("7c");
  const page = await as(browser, r, "accountant");
  await settle(page);
  const opened = await openTask(page, r, /MEMO-2026\/001|Оплата доставки/);
  obs(r, "открыто", { sees: `${page.url()}\n${(await seen(page, PANEL, 2000)) || (await seen(page, "main", 2000))}` });
  obs(r, "кнопки", { sees: (await buttonsOf(page, "body")).join(" | ") });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/7c-open-1440.png` });
  const toFinance = page.getByRole("button", { name: /Оплатить в «Финансы»/ }).or(page.getByRole("link", { name: /Оплатить в «Финансы»/ })).first();
  if (await toFinance.isVisible().catch(() => false)) {
    await step(page, r, "«Оплатить в «Финансы»»", async () => { await toFinance.click(); await page.waitForTimeout(2500); await settle(page); });
    obs(r, "экран оплаты", { sees: `${page.url()}\n${(await seen(page, ".ant-drawer:visible, [role=dialog]:visible", 2500)) || (await seen(page, "main", 2500))}` });
    await page.screenshot({ path: `${process.env.QA_SHOTS}/7c-pay-1440.png` });
  } else if (!opened) {
    await spaGoto(page, "/erp/finance/payments?tab=memos");
    await settle(page);
    obs(r, "«Финансы» напрямую", { sees: `${page.url()}\n${await seen(page, "main", 2000)}` });
  }
  const form = page.locator(PANEL);
  const amount = form.getByLabel(/^Сумма оплаты/);
  obs(r, "форма оплаты", { sees: `сумма: «${await amount.inputValue().catch(() => "?")}»; дата: «${await form.getByLabel("Дата платежа").inputValue().catch(() => "?")}»` });
  await step(page, r, "платёжка и «Оплачено»", async () => {
    const date = form.getByLabel("Дата платежа");
    if (!(await date.inputValue().catch(() => ""))) { await date.click(); await page.keyboard.type("19.11.2026"); await page.keyboard.press("Enter"); }
    if (!(await amount.inputValue().catch(() => ""))) await amount.fill("1500000");
    const file = form.locator('input[type="file"]').first();
    if (await file.count()) { await file.setInputFiles(process.env.SC2_COURIER); await page.waitForTimeout(2500); }
    obs(r, "форма перед «Оплачено»", { sees: (await seen(page, PANEL, 4000)).slice(0, 1600) });
    await page.screenshot({ path: `${process.env.QA_SHOTS}/7c-form-1440.png` });
    await form.getByRole("button", { name: "Оплачено", exact: true }).click();
    await page.waitForTimeout(1200);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) { obs(r, "окно", { sees: await seen(page, '[role="dialog"]', 600) }); await dlg.getByRole("button", { name: "Оплачено" }).click(); }
    await page.waitForTimeout(3500);
    await settle(page);
  });
  const e = (await page.locator(".ant-message:visible, [role=alert]:visible, .ant-form-item-explain-error:visible").allInnerTexts()).join(" | ");
  if (e) obs(r, "сообщения", { sees: e });
  obs(r, "после оплаты", { sees: `${page.url()}\n${(await seen(page, PANEL, 1500)) || (await seen(page, "main", 1500))}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/7c-paid-1440.png` });
  r.save();
};

// 7d. Снабженец: колокольчик и карточка служебки после оплаты.
scenarios["7d"] = async (browser) => {
  const r = new Report("7d");
  const page = await as(browser, r, "supply");
  await settle(page);
  await page.locator('[data-tour="bell"]').first().click().catch(() => {});
  await page.waitForTimeout(1500);
  obs(r, "колокольчик", { sees: (await page.locator(".ant-popover:visible, .ant-drawer:visible, [role=dialog]:visible").allInnerTexts()).join(" || ").slice(0, 1500) });
  await page.keyboard.press("Escape");
  await spaGoto(page, "/eds/documents?box=internal&scope=mine&doc=5e3d3229-560e-4406-92ec-3c85319b72b6&panel=open");
  await settle(page);
  obs(r, "карточка служебки", { sees: (await seen(page, PANEL, 2500)) || (await seen(page, "main", 2500)) });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/7d-card-1440.png` });
  r.save();
};
