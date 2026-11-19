// Сценарий 8. Клиент в Кабинете: своя заявка → менеджер видит → клиент следит за ходом; клиент — по проекту до поставки.
import { PANEL, Report, as, np, obs, seen, settle, step } from "./common.mjs";
export const scenarios = {};
const CAB = process.env.QA_CABINET ?? "http://cabinet.localhost:8111";

async function cab(browser, width = 1440) {
  const { page } = await np(browser, width, { storageState: `${process.env.QA_OUT}/cab-state.json` });
  return page;
}

// 8a. Клиент: Кабинет → «Заявки» → «Новая заявка» → что нужно, позиции, файл → «Отправить заявку».
scenarios["8a"] = async (browser) => {
  const r = new Report("8a");
  const page = await cab(browser);
  await page.goto(`${CAB}/`);
  await page.waitForTimeout(3000);
  await settle(page);
  obs(r, "Кабинет: главная", { sees: `${page.url()}\n${await seen(page, "body", 1500)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/8a-home-1440.png` });
  await step(page, r, "«Новая заявка»", async () => {
    const btn = page.getByRole("link", { name: /Новая заявка/ }).or(page.getByRole("button", { name: /Новая заявка/ })).first();
    if (!(await btn.isVisible().catch(() => false))) {
      await page.getByRole("link", { name: /^Заявки/ }).first().click();
      await page.waitForTimeout(2000);
    }
    await page.getByRole("link", { name: /Новая заявка/ }).or(page.getByRole("button", { name: /Новая заявка/ })).first().click();
    await page.waitForTimeout(2500);
  });
  obs(r, "форма", { sees: `${page.url()}\n${await seen(page, "main", 2000)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/8a-form-1440.png` });
  await step(page, r, "что нужно и позиции", async () => {
    await page.getByLabel("Что нужно").fill("Рельсы Р65 и стыковые накладки на ремонт подъездного пути, доставка в Ташкент (ст. Сергели) до 15.12.2026.");
    const lines = page.getByPlaceholder("Например: подшипник 6205-2RS");
    await lines.nth(0).fill("Рельс Р65, длина 25 м");
    const qty = page.getByLabel(/^Количество/);
    const unit = page.getByPlaceholder("шт, м, ч…");
    await qty.nth(0).fill("120");
    await unit.nth(0).fill("т");
    await page.getByRole("button", { name: "Добавить строку" }).click();
    await lines.nth(1).fill("Накладка стыковая Р65");
    await qty.nth(1).fill("400");
    await unit.nth(1).fill("шт");
  });
  await step(page, r, "файл спецификации", async () => {
    const file = page.locator('input[type="file"]').first();
    if (await file.count()) { await file.setInputFiles(process.env.SC2_SPEC); await page.waitForTimeout(3000); }
    else obs(r, "файла нет", { sees: "поля загрузки нет" });
  });
  obs(r, "перед отправкой", { sees: (await seen(page, "main", 3000)).slice(-900) });
  await step(page, r, "«Отправить заявку»", async () => {
    await page.getByRole("button", { name: "Отправить заявку" }).click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) { obs(r, "окно", { sees: await seen(page, '[role="dialog"]', 900) }); await dlg.getByRole("button").last().click(); }
    await page.waitForTimeout(4000);
    await settle(page);
  });
  const msg = (await page.locator("[role=status]:visible, [role=alert]:visible, [data-sonner-toast]").allInnerTexts()).join(" | ");
  if (msg) obs(r, "сообщения", { sees: msg });
  obs(r, "после отправки", { sees: `${page.url()}\n${await seen(page, "main", 2000)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/8a-sent-1440.png` });
  r.save();
};

// 8b. Менеджер: «Главная» — видна ли заявка клиента из Кабинета и куда ведёт.
scenarios["8b"] = async (browser) => {
  const r = new Report("8b");
  const page = await as(browser, r, "manager_all");
  await settle(page);
  obs(r, "«Главная» менеджера", { sees: `${page.url()}\n${await seen(page, "main", 2000)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/8b-home-1440.png` });
  const row = page.locator("main li, main [role=listitem], main .ant-list-item, main tr").filter({ hasText: /Р65|подъездного/ }).last();
  obs(r, "строка заявки клиента", { sees: (await row.innerText().catch(() => "нет")).replace(/\n/g, " · ") });
  const open = row.getByRole("button").or(row.getByRole("link")).first();
  if (await open.isVisible().catch(() => false)) {
    await step(page, r, "«Открыть»", async () => { await open.click(); await page.waitForTimeout(2500); await settle(page); });
    obs(r, "открыто", { sees: `${page.url()}\n${(await seen(page, PANEL, 2000)) || (await seen(page, "main", 2000))}` });
    await page.screenshot({ path: `${process.env.QA_SHOTS}/8b-open-1440.png` });
  }
  r.save();
};

// 8c. Где заявка из Кабинета: «Операции · Заявки» у менеджера; «Главная» директора и снабженца.
scenarios["8c"] = async (browser) => {
  const r = new Report("8c");
  const page = await as(browser, r, "manager_all");
  await settle(page);
  await page.getByRole("link", { name: "Операции" }).first().click().catch(() => {});
  await page.waitForTimeout(2000);
  await settle(page);
  obs(r, "«Операции» менеджера", { sees: `${page.url()}\n${await seen(page, "main", 2500)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/8c-requests-1440.png` });
  const row = page.locator("main tr, main li").filter({ hasText: "RQ-2026-002" }).first();
  obs(r, "строка RQ-2026-002", { sees: (await row.innerText().catch(() => "нет")).replace(/\n/g, " · ") });
  if (await row.isVisible().catch(() => false)) {
    await row.click();
    await page.waitForTimeout(2500);
    await settle(page);
    obs(r, "карточка заявки", { sees: `${page.url()}\n${(await seen(page, PANEL, 2500)) || (await seen(page, "main", 2500))}` });
    await page.screenshot({ path: `${process.env.QA_SHOTS}/8c-request-1440.png` });
  }
  for (const role of ["director", "supply", "admin"]) {
    const p = await as(browser, r, role);
    await settle(p);
    const text = await seen(p, "main", 3000);
    obs(r, `«Главная» ${role}: есть RQ-2026-002 или «Р65»?`, { sees: /RQ-2026-002|Р65/.test(text) ? text.slice(text.search(/RQ-2026-002|Р65/) - 200, text.search(/RQ-2026-002|Р65/) + 300) : `нет; ${text.slice(0, 400)}` });
    await p.close();
  }
  r.save();
};

/** Видимые кнопки области. */
async function buttonsOf(page, selector = "body") {
  return page.locator(`${selector} button:visible, ${selector} a[role=button]:visible, ${selector} a.ant-btn:visible`).evaluateAll((els) =>
    [...new Set(els.map((e) => `${e.innerText.trim().replace(/\s+/g, " ")}${e.disabled ? " [disabled]" : ""}`).filter(Boolean))],
  );
}

// 8d. Директор: «Наложить резолюцию на письмо IN-003/26» (заявка из Кабинета) — форма и решение менеджеру.
scenarios["8d"] = async (browser) => {
  const r = new Report("8d");
  const page = await as(browser, r, "director");
  await settle(page);
  const row = page.locator("main li, main [role=listitem], main .ant-list-item, main tr").filter({ hasText: "IN-003/26" }).last();
  await step(page, r, "«Открыть»", async () => { await row.getByRole("button").or(row.getByRole("link")).first().click(); await page.waitForTimeout(2500); await settle(page); });
  const scope = page.locator(PANEL);
  obs(r, "резолюция по заявке", { sees: `${page.url()}\n${await seen(page, PANEL, 3000)}` });
  obs(r, "кнопки", { sees: (await buttonsOf(page, PANEL)).join(" | ") });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/8d-resolution-1440.png` });
  const dropdown = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option");
  const resp = scope.getByLabel("Ответственный", { exact: true });
  if (await resp.isVisible().catch(() => false)) {
    await step(page, r, "ответственный — менеджер", async () => {
      await resp.click({ force: true });
      await page.keyboard.type("Универс");
      await page.waitForTimeout(1500);
      await dropdown.first().click();
      await page.waitForTimeout(500);
    });
  }
  const submit = scope.getByRole("button", { name: /Наложить резолюцию|Утвердить/ }).first();
  await step(page, r, "«Наложить резолюцию»", async () => {
    await submit.click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) { obs(r, "окно", { sees: await seen(page, '[role="dialog"]', 600) }); await dlg.getByRole("button").last().click(); }
    await page.waitForTimeout(3500);
    await settle(page);
  });
  const e = (await page.locator(".ant-message:visible, .ant-form-item-explain-error:visible").allInnerTexts()).join(" | ");
  if (e) obs(r, "сообщения", { sees: e });
  obs(r, "после резолюции", { sees: `${page.url()}\n${await seen(page, PANEL, 1500)}` });
  r.save();
};

// 8e. Менеджер: задача после резолюции по заявке из Кабинета.
scenarios["8e"] = async (browser) => {
  const r = new Report("8e");
  const page = await as(browser, r, "manager_all");
  await settle(page);
  const text = await seen(page, "main", 3000);
  obs(r, "«Главная» менеджера", { sees: text });
  const row = page.locator("main li, main [role=listitem], main .ant-list-item, main tr").filter({ hasText: /RQ-2026-002|Р65/ }).last();
  const open = row.getByRole("button").or(row.getByRole("link")).first();
  if (await open.isVisible().catch(() => false)) {
    await step(page, r, "«Открыть»", async () => { await open.click(); await page.waitForTimeout(2500); await settle(page); });
    obs(r, "открыто", { sees: `${page.url()}\n${(await seen(page, PANEL, 2500)) || (await seen(page, "main", 2500))}` });
    await page.screenshot({ path: `${process.env.QA_SHOTS}/8e-task-1440.png` });
  }
  r.save();
};

// 8f. Клиент: статус заявки, уведомления Кабинета, «Поставки» и проект PRJ-2026-001 глазами клиента.
scenarios["8f"] = async (browser) => {
  const r = new Report("8f");
  const page = await cab(browser);
  await page.goto(`${CAB}/requests/2`);
  await page.waitForTimeout(2500);
  await settle(page);
  obs(r, "заявка RQ-2026-002 у клиента", { sees: await seen(page, "main", 1200) });
  await page.getByRole("button", { name: /Уведомления/ }).first().click().catch(() => {});
  await page.waitForTimeout(1500);
  obs(r, "уведомления Кабинета", { sees: (await page.locator("[role=dialog]:visible, [data-radix-popper-content-wrapper], [role=menu]:visible").allInnerTexts()).join(" || ").slice(0, 2000) });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/8f-bell-1440.png` });
  await page.keyboard.press("Escape");
  await page.goto(`${CAB}/deliveries`);
  await page.waitForTimeout(2500);
  await settle(page);
  obs(r, "«Поставки»", { sees: await seen(page, "main", 1800) });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/8f-deliveries-1440.png` });
  const deal = page.getByRole("link", { name: /PRJ-2026-001/ }).first();
  if (await deal.isVisible().catch(() => false)) {
    await deal.click();
    await page.waitForTimeout(2500);
    await settle(page);
    obs(r, "проект PRJ-2026-001 у клиента", { sees: `${page.url()}\n${await seen(page, "main", 3000)}` });
    await page.screenshot({ path: `${process.env.QA_SHOTS}/8f-deal-1440.png`, fullPage: false });
  }
  r.save();
};

// 8g. Директор: резолюция по заявке из Кабинета — текст, снабженец, без инженера → «Утвердить резолюцию».
scenarios["8g"] = async (browser) => {
  const r = new Report("8g");
  const page = await as(browser, r, "director");
  await settle(page);
  await page.goto(`${process.env.QA_BASE}/eds/inbox/IN-003%2F26?panel=open&tab=resolution`);
  await page.waitForTimeout(3000);
  await settle(page);
  const scope = page.locator(PANEL);
  const dropdown = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option");
  await step(page, r, "текст и исполнители", async () => {
    await scope.getByLabel("Текст резолюции").fill("Рассчитать по спецификации клиента, срок поставки — до 15.12.2026.");
    const supplySel = scope.locator(".ant-select").first();
    await supplySel.click();
    await page.waitForTimeout(1000);
    obs(r, "сотрудники зоны «Снабженец»", { sees: (await dropdown.allInnerTexts()).join(" | ") });
    await dropdown.first().click();
    await page.waitForTimeout(500);
    const eng = scope.getByRole("checkbox", { name: /Гл\. инженер/ });
    if (await eng.isChecked().catch(() => false)) await eng.uncheck({ force: true });
  });
  await step(page, r, "«Утвердить резолюцию»", async () => {
    await scope.getByRole("button", { name: "Утвердить резолюцию" }).click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) { obs(r, "окно", { sees: await seen(page, '[role="dialog"]', 600) }); await dlg.getByRole("button").last().click(); }
    await page.waitForTimeout(4000);
    await settle(page);
  });
  const e = (await page.locator(".ant-message:visible, .ant-form-item-explain-error:visible").allInnerTexts()).join(" | ");
  if (e) obs(r, "сообщения", { sees: e });
  obs(r, "после резолюции", { sees: `${page.url()}\n${await seen(page, PANEL, 1500)}` });
  r.save();
};

// 8h. Снабженец: задание на расчёт по заявке из Кабинета — есть ли файл клиента; клиент — статус заявки.
scenarios["8h"] = async (browser) => {
  const r = new Report("8h");
  const page = await as(browser, r, "supply");
  await settle(page);
  obs(r, "«Главная» снабженца", { sees: await seen(page, "main", 2000) });
  const row = page.locator("main li, main [role=listitem], main .ant-list-item, main tr").filter({ hasText: /RQ-2026-002|Р65|IN-003/ }).last();
  const open = row.getByRole("button").or(row.getByRole("link")).first();
  if (await open.isVisible().catch(() => false)) {
    await step(page, r, "«Открыть»", async () => { await open.click(); await page.waitForTimeout(2500); await settle(page); });
    const text = (await seen(page, PANEL, 4000)) || (await seen(page, "main", 4000));
    obs(r, "задание на расчёт", { sees: `${page.url()}\n${text}` });
    obs(r, "файл клиента в задании", { sees: /spec\.pdf/.test(text) ? "есть spec.pdf" : "spec.pdf не видно" });
    await page.screenshot({ path: `${process.env.QA_SHOTS}/8h-calc-1440.png` });
  }
  const c = await cab(browser);
  await c.goto(`${CAB}/requests/2`);
  await c.waitForTimeout(2500);
  await settle(c);
  obs(r, "заявка у клиента после резолюции", { sees: (await seen(c, "main", 600)) });
  r.save();
};
