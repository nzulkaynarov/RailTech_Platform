// Сценарий 9. Партнёр: заказ → вход в Кабинет → подтверждение заказа и срока → сотрудник видит ответ.
import { execSync } from "node:child_process";
import { PANEL, Report, as, np, obs, seen, settle, spaGoto, step } from "./common.mjs";
export const scenarios = {};
const CAB = process.env.QA_CABINET ?? "http://cabinet.localhost:8111";

function mailbox() {
  return JSON.parse(execSync("docker exec rt-scen-mailpit wget -qO- http://localhost:8025/api/v1/messages", { encoding: "utf8" })).messages ?? [];
}
function mailText(id) {
  const m = JSON.parse(execSync(`docker exec rt-scen-mailpit wget -qO- http://localhost:8025/api/v1/message/${id}`, { encoding: "utf8" }));
  return { subject: m.Subject, text: m.Text ?? "" };
}
async function buttonsOf(page, selector = "body") {
  return page.locator(`${selector} button:visible, ${selector} a[role=button]:visible, ${selector} a.ant-btn:visible`).evaluateAll((els) =>
    [...new Set(els.map((e) => `${e.innerText.trim().replace(/\s+/g, " ")}${e.disabled ? " [disabled]" : ""}`).filter(Boolean))],
  );
}

// 9a. Снабженец: «Контакты» → партнёр «ООО Демо Сталь» → карточка — есть ли приглашение в Кабинет; заказ PO-2026-001 — что видит.
scenarios["9a"] = async (browser) => {
  const r = new Report("9a");
  const page = await as(browser, r, "supply");
  await settle(page);
  await page.getByRole("link", { name: "Контакты" }).first().click();
  await page.waitForTimeout(2500);
  await settle(page);
  obs(r, "«Контакты» снабженца", { sees: `${page.url()}\n${await seen(page, "main", 1500)}` });
  const partner = page.getByText("Демо Сталь").first();
  if (await partner.isVisible().catch(() => false)) {
    await step(page, r, "карточка «ООО Демо Сталь»", async () => { await partner.click(); await page.waitForTimeout(2500); await settle(page); });
    obs(r, "карточка партнёра", { sees: `${page.url()}\n${(await seen(page, PANEL, 2500)) || (await seen(page, "main", 2500))}` });
    obs(r, "кнопки", { sees: (await buttonsOf(page, "body")).join(" | ") });
    await page.screenshot({ path: `${process.env.QA_SHOTS}/9a-partner-1440.png` });
  } else {
    const tabs = await buttonsOf(page, "main");
    obs(r, "партнёра в списке нет", { sees: tabs.join(" | ") });
  }
  r.save();
};

// 9b. Снабженец: «Пригласить» партнёра в Кабинет → письмо партнёру.
scenarios["9b"] = async (browser) => {
  const r = new Report("9b");
  const page = await as(browser, r, "supply");
  await settle(page);
  await spaGoto(page, "/crm/clients?partner=3&panel=open&tab=card");
  await settle(page);
  const before = mailbox().length;
  await step(page, r, "«Пригласить»", async () => {
    await page.getByRole("button", { name: "Пригласить" }).first().click();
    await page.waitForTimeout(1500);
  });
  const dlg = page.locator("[role=dialog]:visible, .ant-drawer:visible").last();
  obs(r, "окно приглашения", { sees: await dlg.innerText().catch(() => "нет окна") });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/9b-invite-1440.png` });
  const email = dlg.getByLabel(/почта|E-mail|Email/i).first();
  if (await email.isVisible().catch(() => false) && !(await email.inputValue())) await email.fill("partner.sc2@demo.example");
  const send = dlg.getByRole("button", { name: /Пригласить|Отправить/ }).last();
  if (await send.isVisible().catch(() => false)) {
    await step(page, r, "отправить приглашение", async () => { await send.click(); await page.waitForTimeout(5000); });
  }
  const e = (await page.locator(".ant-message:visible, .ant-form-item-explain-error:visible, [role=alert]:visible").allInnerTexts()).join(" | ");
  if (e) obs(r, "сообщения", { sees: e });
  const fresh = mailbox().slice(0, Math.max(0, mailbox().length - before));
  for (const m of fresh) obs(r, `письмо «${m.Subject}»`, { sees: `кому: ${m.To.map((x) => x.Address).join(", ")}\n${mailText(m.ID).text.slice(0, 900)}` });
  r.save();
};

// 9c. Партнёр: ссылка из приглашения → Кабинет → «Заказы» → PO-2026-001 → подтвердить и срок.
scenarios["9c"] = async (browser) => {
  const r = new Report("9c");
  const { page } = await np(browser, 1440);
  const invite = mailbox().find((m) => /Приглашение в личный кабинет «ООО Демо Сталь»/.test(m.Subject));
  const link = /(http:\/\/cabinet\.localhost:8111\/auth\/magic#token=\S+)/.exec(invite ? mailText(invite.ID).text : "")?.[1];
  r.check("ссылка из приглашения найдена", !!link);
  await page.goto(link);
  await page.waitForTimeout(4000);
  await settle(page);
  obs(r, "Кабинет партнёра после входа", { sees: `${page.url()}\n${await seen(page, "body", 2000)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/9c-home-1440.png` });
  await page.context().storageState({ path: `${process.env.QA_OUT}/partner-state.json` });
  await page.goto(`${CAB}/partner/orders`);
  await page.waitForTimeout(3000);
  await settle(page);
  obs(r, "«Заказы» партнёра", { sees: `${page.url()}\n${await seen(page, "main", 2000)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/9c-orders-1440.png` });
  const po = page.getByText("PO-2026-001").first();
  if (await po.isVisible().catch(() => false)) {
    await step(page, r, "заказ PO-2026-001", async () => { await po.click(); await page.waitForTimeout(2500); await settle(page); });
    obs(r, "заказ у партнёра", { sees: `${page.url()}\n${await seen(page, "main", 2500)}` });
    obs(r, "кнопки", { sees: (await buttonsOf(page, "main")).join(" | ") });
    await page.screenshot({ path: `${process.env.QA_SHOTS}/9c-order-1440.png` });
  }
  r.save();
};

// 9d. Снабженец: контакт партнёра → «Может создавать запросы и загружать файлы» → сохранить.
scenarios["9d"] = async (browser) => {
  const r = new Report("9d");
  const page = await as(browser, r, "supply");
  await spaGoto(page, "/crm/clients?partner=3&panel=open&tab=card");
  await settle(page);
  const panel = page.locator(PANEL);
  obs(r, "контакты партнёра", { sees: (await seen(page, PANEL, 6000)).split("Контакты")[1]?.slice(0, 700) ?? "" });
  await step(page, r, "«Изменить контакт»", async () => {
    await panel.getByRole("button", { name: /Изменить контакт/ }).first().click();
    await page.waitForTimeout(1500);
  });
  const form = page.locator("[role=dialog]:visible, .ant-drawer:visible").last();
  obs(r, "форма контакта", { sees: await form.innerText().catch(() => "нет") });
  await step(page, r, "право и сохранить", async () => {
    const box = form.getByRole("switch", { name: /Может создавать запросы/ }).or(form.getByRole("checkbox", { name: /Может создавать запросы/ })).first();
    obs(r, "право в форме до", { sees: `aria-checked=${await box.getAttribute("aria-checked")} checked=${await box.isChecked().catch(() => "?")}` });
    await page.screenshot({ path: `${process.env.QA_SHOTS}/9d-contact-form-1440.png` });
    if (!(await box.isChecked().catch(() => false))) await box.click({ force: true });
    await form.getByRole("button", { name: /Сохранить|Готово|Изменить/ }).last().click();
    await page.waitForTimeout(2500);
  });
  const e = (await page.locator(".ant-message:visible, .ant-form-item-explain-error:visible").allInnerTexts()).join(" | ");
  if (e) obs(r, "сообщения", { sees: e });
  obs(r, "контакты после", { sees: (await seen(page, PANEL, 6000)).split("Контакты")[1]?.slice(0, 500) ?? "" });
  r.save();
};

// 9e. Снабженец: новый заказ партнёру вручную — строка, цена, дата → черновик → «Отправить партнёру».
scenarios["9e"] = async (browser) => {
  const r = new Report("9e");
  const page = await as(browser, r, "supply");
  await spaGoto(page, "/erp/stock/new");
  await settle(page);
  const main = page.locator("main");
  const dropdown = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option");
  await step(page, r, "партнёр, «Вручную»", async () => {
    await main.getByRole("combobox").first().click();
    await page.keyboard.type("Демо Сталь");
    await page.waitForTimeout(1500);
    await dropdown.filter({ hasText: "Демо Сталь" }).first().click();
    await main.getByText("Вручную", { exact: true }).click();
    await main.getByRole("button", { name: /^Далее/ }).first().click();
    await page.waitForTimeout(2000);
  });
  await step(page, r, "дата, строка: товар, кол-во, цена", async () => {
    const date = main.getByLabel("Ожидаемая дата");
    await date.click();
    await page.keyboard.type("10.12.2026");
    await page.keyboard.press("Enter");
    await main.locator('.ant-select[aria-label="Товар, строка 1"]').click();
    await page.keyboard.type("Рельс");
    await page.waitForTimeout(2000);
    obs(r, "подсказки товара", { sees: (await dropdown.allInnerTexts()).join(" | ") || "пусто" });
    await dropdown.first().click();
    obs(r, "поля строки", { sees: (await main.locator("input:visible").evaluateAll((els) => els.map((e) => `${e.getAttribute("aria-label") ?? e.id}`))).join(" | ") });
    await main.locator('input[aria-label^="Кол-во"], input[aria-label^="Количество"]').first().fill("20");
    await main.locator('input[aria-label^="Цена"]').first().fill("9500000");
  });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/9e-lines-1440.png` });
  await step(page, r, "«Создать черновик»", async () => {
    await main.getByRole("button", { name: "Создать черновик" }).click();
    await page.waitForTimeout(4000);
    await settle(page);
  });
  const e = (await page.locator(".ant-message:visible, .ant-form-item-explain-error:visible").allInnerTexts()).join(" | ");
  if (e) obs(r, "сообщения", { sees: e });
  obs(r, "черновик заказа", { sees: `${page.url()}\n${await seen(page, "main", 1600)}` });
  const before = mailbox().length;
  await step(page, r, "«Отправить партнёру»", async () => {
    await page.getByRole("button", { name: "Отправить партнёру" }).first().click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) { obs(r, "окно отправки", { sees: await seen(page, '[role="dialog"]', 900) }); await dlg.getByRole("button").last().click(); }
    await page.waitForTimeout(6000);
    await settle(page);
  });
  obs(r, "заказ после отправки", { sees: `${page.url()}\n${await seen(page, "main", 1200)}` });
  for (const m of mailbox().slice(0, Math.max(0, mailbox().length - before))) {
    obs(r, `письмо «${m.Subject}»`, { sees: `кому: ${m.To.map((x) => x.Address).join(", ")}\n${mailText(m.ID).text.slice(0, 900)}` });
  }
  r.save();
};

// 9f. Партнёр: ссылка из письма → PO-2026-002 → «Подтвердить» (срок) → итог.
scenarios["9f"] = async (browser) => {
  const r = new Report("9f");
  const { page } = await np(browser, 1440, { storageState: `${process.env.QA_OUT}/partner-state.json` });
  await page.goto(`${CAB}/partner/orders?orderId=2`);
  await page.waitForTimeout(3500);
  await settle(page);
  const drawer = page.locator("[role=dialog]:visible").last();
  obs(r, "заказ PO-2026-002 у партнёра", { sees: `${page.url()}\n${(await drawer.innerText().catch(() => "")) || (await seen(page, "main", 2500))}` });
  obs(r, "кнопки", { sees: (await buttonsOf(page, "body")).join(" | ") });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/9f-order-1440.png` });
  const confirm = drawer.getByRole("button", { name: /^Подтвердить/ }).first();
  if (await confirm.isVisible().catch(() => false)) {
    await step(page, r, "«Подтвердить»", async () => {
      await confirm.click();
      await page.waitForTimeout(1500);
      obs(r, "окно подтверждения", { sees: (await page.locator("[role=dialog]:visible, [role=alertdialog]:visible").allInnerTexts()).join(" || ") });
      await page.screenshot({ path: `${process.env.QA_SHOTS}/9f-confirm-1440.png` });
      const dlg = page.locator("[role=dialog]:visible, [role=alertdialog]:visible").last();
      const date = dlg.getByLabel(/дата|срок/i).first();
      if (await date.isVisible().catch(() => false) && !(await date.inputValue().catch(() => ""))) await date.fill("2026-12-08");
      await dlg.getByRole("button", { name: /Подтвердить/ }).last().click();
      await page.waitForTimeout(4000);
      await settle(page);
    });
    const msg = (await page.locator("[role=status]:visible, [role=alert]:visible, [data-sonner-toast]").allInnerTexts()).join(" | ");
    if (msg) obs(r, "сообщения", { sees: msg });
    obs(r, "после подтверждения", { sees: (await page.locator("[role=dialog]:visible").last().innerText().catch(() => "")) || (await seen(page, "main", 1500)) });
  }
  r.save();
};

// 9g. Снабженец: видно ли подтверждение партнёра — «Главная», колокольчик, заказ.
scenarios["9g"] = async (browser) => {
  const r = new Report("9g");
  const page = await as(browser, r, "supply");
  await settle(page);
  obs(r, "«Главная» снабженца", { sees: await seen(page, "main", 1500) });
  await page.locator('[data-tour="bell"]').first().click().catch(() => {});
  await page.waitForTimeout(1500);
  obs(r, "колокольчик", { sees: (await page.locator(".ant-popover:visible, .ant-drawer:visible, [role=dialog]:visible").allInnerTexts()).join(" || ").slice(0, 900) });
  await page.keyboard.press("Escape");
  await spaGoto(page, "/erp/stock/PO-2026-002");
  await settle(page);
  obs(r, "заказ PO-2026-002", { sees: await seen(page, "main", 2000) });
  r.save();
};
