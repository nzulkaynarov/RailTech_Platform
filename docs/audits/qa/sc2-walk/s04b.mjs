import { Report, as, obs, seen, settle, spaGoto } from "./common.mjs";
export const scenarios = {};
// 4e. Снабженец и МУ: «Заказы» и «Новый заказ» по прямому адресу — видны ли и кому.
scenarios["4e"] = async (browser) => {
  const r = new Report("4e");
  for (const role of ["supply", "manager_all"]) {
    const page = await as(browser, r, role);
    for (const path of ["/erp/stock?view=orders", "/erp/stock/new"]) {
      await spaGoto(page, path);
      await settle(page);
      obs(r, `${role} ${path}`, { sees: `${page.url()}\n${(await seen(page, "main", 1400))}` });
    }
    await page.close();
  }
  r.save();
};

import { PANEL, step } from "./common.mjs";
// 4f. Снабженец: новый заказ → партнёр «ООО Демо Сталь» → «На дефицит заявки» → строки → черновик.
scenarios["4f"] = async (browser) => {
  const r = new Report("4f");
  const page = await as(browser, r, "supply");
  await spaGoto(page, "/erp/stock/new");
  await settle(page);
  const main = page.locator("main");
  await step(page, r, "партнёр и способ", async () => {
    await main.getByRole("combobox").first().click();
    await page.keyboard.type("Демо Сталь");
    await page.waitForTimeout(1500);
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option", { hasText: "Демо Сталь" }).first().click();
    await main.getByText("На дефицит заявки", { exact: true }).click();
    await main.getByLabel("Номер заявки или проекта").fill("PRJ-2026-001");
    await main.getByRole("button", { name: "Создать черновик" }).click();
    await page.waitForTimeout(4000);
    await settle(page);
  });
  obs(r, "после «Создать черновик»", { sees: `${page.url()}\n${await seen(page, "main", 2500)}` });
  const err = await seen(page, ".ant-message, .ant-notification, [role=alert], .ant-form-item-explain-error", 500);
  if (err) obs(r, "сообщение", { sees: err });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/4f-order-lines-1440.png` });
  r.save();
};

import { mailbox, mailText } from "./s02.mjs";
// 4g. Снабженец: «Отправить партнёру» (без цены и ожидаемой даты) → письмо партнёру.
scenarios["4g"] = async (browser) => {
  const r = new Report("4g");
  const page = await as(browser, r, "supply");
  await spaGoto(page, "/erp/stock/PO-2026-001");
  await settle(page);
  const before = mailbox().length;
  await step(page, r, "«Отправить партнёру»", async () => {
    await page.getByRole("button", { name: "Отправить партнёру" }).first().click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) { obs(r, "окно отправки", { sees: await seen(page, '[role="dialog"]', 900) }); await dlg.getByRole("button").last().click(); }
    await page.waitForTimeout(6000);
    await settle(page);
  });
  obs(r, "заказ после отправки", { sees: (await seen(page, "main", 1500)) });
  for (const m of mailbox().slice(0, Math.max(0, mailbox().length - before))) {
    const t = mailText(m.ID);
    obs(r, `письмо «${t.subject}»`, { sees: `кому: ${m.To.map((x) => x.Address).join(", ")}; вложения: ${t.attachments.join(", ") || "—"}\n${t.text.slice(0, 900)}` });
  }
  r.save();
};

// 4h. Снабженец: «Партнёр подтвердил» → приёмка всего заказа → что дальше (резерв, отгрузка).
scenarios["4h"] = async (browser) => {
  const r = new Report("4h");
  const page = await as(browser, r, "supply");
  await spaGoto(page, "/erp/stock/PO-2026-001");
  await settle(page);
  for (const name of ["Партнёр подтвердил", "Принять", "Приёмка", "Принять товар"]) {
    const btn = page.getByRole("button", { name, exact: true }).first();
    if (!(await btn.isVisible().catch(() => false))) continue;
    await step(page, r, `«${name}»`, async () => {
      await btn.click();
      await page.waitForTimeout(1500);
      const dlg = page.getByRole("dialog");
      const pnl = page.locator(PANEL);
      const box = (await dlg.isVisible().catch(() => false)) ? dlg : pnl;
      obs(r, `форма «${name}»`, { sees: await seen(page, (await dlg.isVisible().catch(() => false)) ? '[role="dialog"]' : PANEL, 1200) });
      const qty = box.getByLabel(/Принято|Количество|Получено/).first();
      if (await qty.isVisible().catch(() => false)) await qty.fill("40");
      const date = box.getByLabel(/Дата|Ожидаемая/).first();
      if (await date.isVisible().catch(() => false) && !(await date.inputValue().catch(() => ""))) { await date.fill("25.11.2026"); await page.keyboard.press("Enter"); }
      await box.getByRole("button", { name: /Подтвердить|Принять|Сохранить|Оприходовать/ }).last().click();
      await page.waitForTimeout(5000);
      await settle(page);
    });
    const err = await seen(page, ".ant-message, .ant-notification, [role=alert], .ant-form-item-explain-error", 500);
    if (err) obs(r, `сообщение после «${name}»`, { sees: err });
    obs(r, `заказ после «${name}»`, { sees: (await seen(page, "main", 1200)) });
  }
  await page.screenshot({ path: `${process.env.QA_SHOTS}/4h-order-received-1440.png` });
  r.save();
};

// 4i. Снабженец: «Партнёр подтвердил» — дата через календарь, снимок перед подтверждением.
scenarios["4i"] = async (browser) => {
  const r = new Report("4i");
  const page = await as(browser, r, "supply");
  await spaGoto(page, "/erp/stock/PO-2026-001");
  await settle(page);
  await page.getByRole("button", { name: "Партнёр подтвердил", exact: true }).first().click();
  await page.waitForTimeout(1200);
  const dlg = page.getByRole("dialog").filter({ hasText: "Партнёр подтвердил заказ" });
  await step(page, r, "дата подтверждения", async () => {
    await dlg.locator("input").first().click();
    await page.waitForTimeout(600);
    await page.keyboard.type("25.11.2026");
    await page.waitForTimeout(600);
    await page.locator(".ant-picker-dropdown:not(.ant-picker-dropdown-hidden) .ant-picker-cell-in-view", { hasText: /^25$/ }).first().click().catch(() => {});
    await page.waitForTimeout(600);
  });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/4i-confirm-dialog-1440.png` });
  obs(r, "окно перед «Подтвердить»", { sees: `${await seen(page, '[role="dialog"]', 600)}\nзначение даты: ${await dlg.locator("input").first().inputValue().catch(() => "?")}` });
  await step(page, r, "«Подтвердить»", async () => {
    await dlg.getByRole("button", { name: "Подтвердить" }).click();
    await page.waitForTimeout(4000);
    await settle(page);
  });
  const t = await seen(page, "main", 900);
  obs(r, "заказ после подтверждения", { sees: t });
  r.save();
};

// 4j. Снабженец: «Принять товар» — форма приёмки, 40 т, что дальше (склад, резерв под проект, отгрузка).
scenarios["4j"] = async (browser) => {
  const r = new Report("4j");
  const page = await as(browser, r, "supply");
  await spaGoto(page, "/erp/stock/PO-2026-001");
  await settle(page);
  await page.getByRole("button", { name: "Принять товар", exact: true }).first().click();
  await page.waitForTimeout(2000);
  const dlgOpen = await page.getByRole("dialog").isVisible().catch(() => false);
  const sel = dlgOpen ? '[role="dialog"]' : PANEL;
  obs(r, "форма приёмки", { sees: `${page.url()}\n${await seen(page, sel, 1500)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/4j-receipt-form-1440.png` });
  const box = page.locator(sel).first();
  await step(page, r, "приёмка 40 т", async () => {
    const qty = box.getByLabel(/Принято|Количество|Получено|Факт/).first();
    if (await qty.isVisible().catch(() => false)) { await qty.fill("40"); }
    await box.getByRole("button", { name: /Принять|Оприходовать|Сохранить|Провести/ }).last().click();
    await page.waitForTimeout(6000);
    await settle(page);
  });
  const err = await seen(page, ".ant-message, .ant-notification, [role=alert], .ant-form-item-explain-error", 500);
  if (err) obs(r, "сообщение", { sees: err });
  obs(r, "заказ после приёмки", { sees: (await seen(page, "main", 1600)) });
  r.save();
};

// 4k. После приёмки: остатки и резерв под проект, «Задачи» снабженца и менеджера, отгрузки.
scenarios["4k"] = async (browser) => {
  const r = new Report("4k");
  const page = await as(browser, r, "supply");
  await spaGoto(page, "/erp/stock");
  await settle(page);
  obs(r, "остатки и резервы", { sees: (await seen(page, "main", 1500)) });
  await spaGoto(page, "/erp/stock?view=shipments");
  await settle(page);
  obs(r, "отгрузки", { sees: (await seen(page, "main", 1500)) });
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  const q = await seen(page, "main", 1500);
  obs(r, "«Задачи» снабженца", { sees: q.slice(q.indexOf("Что сделать сейчас")) });
  await page.close();
  const pm = await as(browser, r, "manager_all");
  await spaGoto(pm, "/dashboard/queue");
  await settle(pm);
  const qm = await seen(pm, "main", 1500);
  obs(r, "«Задачи» менеджера", { sees: qm.slice(qm.indexOf("Что сделать сейчас")) });
  r.save();
};

// 4l. Снабженец: «Новая отгрузка по проекту» PRJ-2026-001 → резервы → отгрузить.
scenarios["4l"] = async (browser) => {
  const r = new Report("4l");
  const page = await as(browser, r, "supply");
  await spaGoto(page, "/erp/stock?view=shipments");
  await settle(page);
  const main = page.locator("main");
  await step(page, r, "«Найти резервы» по проекту", async () => {
    await main.getByPlaceholder("ПР-2026-099").fill("PRJ-2026-001");
    await main.getByRole("button", { name: "Найти резервы" }).click();
    await page.waitForTimeout(3000);
    await settle(page);
  });
  obs(r, "резервы проекта", { sees: (await seen(page, "main", 2000)).split("Новая отгрузка по проекту")[1]?.slice(0, 1200) ?? "" });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/4l-shipment-reserves-1440.png` });
  const ship = main.getByRole("button", { name: /Отгрузить|Оформить отгрузку|Создать отгрузку/ }).first();
  if (await ship.isVisible().catch(() => false)) {
    await step(page, r, "отгрузка", async () => {
      await ship.click();
      await page.waitForTimeout(1500);
      const dlg = page.getByRole("dialog");
      if (await dlg.isVisible().catch(() => false)) { obs(r, "окно отгрузки", { sees: await seen(page, '[role="dialog"]', 900) }); await dlg.getByRole("button", { name: /Отгрузить|Оформить|Подтвердить|Создать/ }).last().click(); }
      await page.waitForTimeout(5000);
      await settle(page);
    });
    const err = await seen(page, ".ant-message, .ant-notification, [role=alert], .ant-form-item-explain-error", 500);
    if (err) obs(r, "сообщение", { sees: err });
    obs(r, "после отгрузки", { sees: (await seen(page, "main", 1600)).split("Отгрузки")[2]?.slice(0, 1000) ?? (await seen(page, "main", 1600)) });
  }
  r.save();
};

// 4m. После отгрузки: список отгрузок, проект (исполнение), письма клиенту.
scenarios["4m"] = async (browser) => {
  const r = new Report("4m");
  const page = await as(browser, r, "manager_all");
  await spaGoto(page, "/erp/stock?view=shipments");
  await settle(page);
  const t = await seen(page, "main", 2500);
  obs(r, "отгрузки", { sees: t.slice(t.lastIndexOf("Отгрузки")) });
  await spaGoto(page, "/eds/projects/PRJ-2026-001");
  await settle(page);
  const p = await seen(page, "main", 5000);
  obs(r, "проект: исполнение", { sees: p.slice(p.indexOf("Исполнение"), p.indexOf("Исполнение") + 900) });
  obs(r, "письма в Mailpit (последние 4)", { sees: mailbox().slice(0, 4).map((m) => `${m.Subject} → ${m.To.map((x) => x.Address).join(", ")}`).join("\n") });
  r.save();
};

// 4n. Менеджер: «Отправлено, в пути» → «Доставлено» — формы и что видит клиент.
scenarios["4n"] = async (browser) => {
  const r = new Report("4n");
  const page = await as(browser, r, "manager_all");
  for (const name of ["Отправлено, в пути", "Доставлено"]) {
    await spaGoto(page, "/eds/projects/PRJ-2026-001");
    await settle(page);
    const before = mailbox().length;
    await step(page, r, `«${name}»`, async () => {
      await page.getByRole("button", { name, exact: true }).first().click();
      await page.waitForTimeout(1500);
      const dlg = page.getByRole("dialog");
      if (await dlg.isVisible().catch(() => false)) {
        obs(r, `окно «${name}»`, { sees: await seen(page, '[role="dialog"]', 900) });
        const file = dlg.locator('input[type="file"]');
        if (await file.count()) await file.first().setInputFiles(process.env.SC2_LETTER);
        await dlg.getByRole("button", { name: /Отметить|Сохранить|Подтвердить|Доставлено|Отправлено/ }).last().click();
      }
      await page.waitForTimeout(5000);
      await settle(page);
    });
    const err = await seen(page, ".ant-message, .ant-notification, [role=alert], .ant-form-item-explain-error", 500);
    if (err) obs(r, `сообщение после «${name}»`, { sees: err });
    const p = await seen(page, "main", 5000);
    obs(r, `исполнение после «${name}»`, { sees: p.slice(p.indexOf("Отгрузка\nСтатус"), p.indexOf("Отгрузка\nСтатус") + 500) });
    for (const m of mailbox().slice(0, Math.max(0, mailbox().length - before))) obs(r, `письмо «${m.Subject}»`, { sees: `кому: ${m.To.map((x) => x.Address).join(", ")}` });
  }
  const q = await (async () => { await spaGoto(page, "/dashboard/queue"); await settle(page); return seen(page, "main", 1500); })();
  obs(r, "«Задачи» менеджера", { sees: q.slice(q.indexOf("Что сделать сейчас")) });
  r.save();
};

// 4o. Менеджер: «Выпустить акт» → акт → письмо клиенту; имя PDF акта.
scenarios["4o"] = async (browser) => {
  const r = new Report("4o");
  const page = await as(browser, r, "manager_all");
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  await page.getByRole("link", { name: /Открыть/ }).first().click();
  await page.waitForTimeout(3000);
  await settle(page);
  obs(r, "экран из строки «Выпустить акт»", { sees: `${page.url()}\n${await seen(page, PANEL, 1500)}` });
  const before = mailbox().length;
  const btn = page.locator(PANEL).getByRole("button", { name: /Выпустить акт/ }).first();
  obs(r, "кнопка «Выпустить акт»", { sees: `видна: ${await btn.isVisible().catch(() => false)}, активна: ${await btn.isEnabled().catch(() => false)}` });
  if (await btn.isEnabled().catch(() => false)) {
    await step(page, r, "«Выпустить акт»", async () => {
      await btn.click();
      await page.waitForTimeout(1500);
      const dlg = page.getByRole("dialog");
      if (await dlg.isVisible().catch(() => false)) { obs(r, "окно", { sees: await seen(page, '[role="dialog"]', 600) }); await dlg.getByRole("button").last().click(); }
      await page.waitForTimeout(8000);
      await settle(page);
    });
    obs(r, "после «Выпустить акт»", { sees: await seen(page, PANEL, 1500) });
    for (const m of mailbox().slice(0, Math.max(0, mailbox().length - before))) {
      const t = mailText(m.ID);
      obs(r, `письмо «${t.subject}»`, { sees: `кому: ${m.To.map((x) => x.Address).join(", ")}; вложения: ${t.attachments.join(", ") || "—"}\n${t.text.slice(0, 400)}` });
    }
  }
  r.save();
};

import { np } from "./common.mjs";
const CAB = process.env.QA_CABINET ?? "http://cabinet.localhost:8111";
// 4p. Клиент: «Акты» → акт → «Принять» → итог; что видит проект после этого.
scenarios["4p"] = async (browser) => {
  const r = new Report("4p");
  const { page } = await np(browser, 1440, { storageState: `${process.env.QA_OUT}/cab-state.json` });
  await page.goto(`${CAB}/acts?focus=1`);
  await page.waitForTimeout(3000);
  await settle(page);
  obs(r, "акты у клиента", { sees: await seen(page, "main", 1200) });
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: 15000 }).catch(() => null),
    page.getByRole("button", { name: /Скачать/ }).or(page.getByRole("link", { name: /Скачать/ })).first().click().catch(() => {}),
  ]);
  obs(r, "имя PDF акта в Кабинете", { sees: download ? download.suggestedFilename() : "скачивание не началось" });
  const before = mailbox().length;
  await step(page, r, "«Принять» акт", async () => {
    await page.getByRole("button", { name: /^Принять/ }).first().click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) {
      obs(r, "окно приёмки акта", { sees: await seen(page, '[role="dialog"]', 900) });
      const getCode = dlg.getByRole("button", { name: /Получить код/ });
      if (await getCode.isVisible().catch(() => false)) {
        await getCode.click();
        await page.waitForTimeout(5000);
        const code = /\b(\d{6})\b/.exec(mailbox().slice(0, Math.max(0, mailbox().length - before)).map((m) => mailText(m.ID).text).join("\n"))?.[1];
        await dlg.getByRole("textbox").first().fill(code ?? "");
      }
      await dlg.getByRole("button", { name: /Принять|Подтвердить/ }).last().click();
    }
    await page.waitForTimeout(5000);
    await settle(page);
  });
  obs(r, "после приёмки акта", { sees: await seen(page, "main", 1200) });
  await page.close();
  const pm = await as(browser, r, "manager_all");
  await spaGoto(pm, "/eds/projects/PRJ-2026-001?panel=open&tab=act");
  await settle(pm);
  const t = await seen(pm, "main", 1200);
  obs(r, "проект после приёмки акта", { sees: `${t.slice(0, 400)}\nпанель: ${await seen(pm, PANEL, 700)}` });
  await spaGoto(pm, "/dashboard/queue");
  await settle(pm);
  const q = await seen(pm, "main", 1200);
  obs(r, "«Задачи» менеджера", { sees: q.slice(q.indexOf("Что сделать сейчас")) });
  r.save();
};
