import { screenHere, ADMIN, PEOPLE, PANEL, Report, bff, compose, np, pwOf, saveState, screen, secret, settle, shot, signIn, spaGoto, state, step, toastsGone } from "./common.mjs";
export const scenarios = {};
const txt = async (page, sel = "#main-content") => (await page.locator(sel).first().innerText().catch(() => "")).replace(/\n{2,}/g, "\n");
const out = (label, t, n = 1200) => console.log(`--- ${label}\n${String(t).slice(0, n)}`);
const DEAL2 = "ЗВ-2026-002";

// e1. Исключение: ЗВ-2026-002 — МУ считает одну строку-товар, визирует (снабжение), «Расчёт готов»
scenarios.e1 = async (browser) => {
  const r = new Report("e1");
  const mu = PEOPLE.manager_all;
  const deal = process.env.DEAL ?? DEAL2;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, `/erp/calc/${encodeURIComponent(deal)}`);
  await settle(page);
  if (await page.getByRole("button", { name: "Начать расчёт" }).count()) {
    await page.getByRole("button", { name: "Начать расчёт" }).click();
    await page.waitForTimeout(2000);
  }
  if (!(await page.locator("table tbody tr").count())) {
    await step(page, r, "МУ добавляет строку «Шпала ЖБ»", async () => {
      await page.getByRole("button", { name: "Добавить строку" }).first().click();
      const dlg = page.getByRole("dialog");
      await dlg.getByLabel("Наименование").fill("Шпала железобетонная Ш1");
      await dlg.getByLabel("Количество").fill("500");
      await dlg.getByLabel("Единица").fill("шт.");
      await dlg.getByRole("button", { name: "Добавить", exact: true }).click();
      await page.waitForTimeout(1500);
    });
  }
  const row = page.locator("table tbody tr").first();
  const fillNum = async (loc, v) => { await loc.fill(v); await loc.blur(); await page.waitForTimeout(800); };
  await fillNum(row.getByLabel(/^Закупка за единицу/), process.env.COST ?? "400000");
  await fillNum(row.getByLabel(/^Цена клиенту/), process.env.PRICE ?? "520000");
  await step(page, r, "МУ визирует строку (снабжение)", async () => { await row.getByRole("button", { name: /Подтвердить/ }).click(); await page.waitForTimeout(1500); });
  await step(page, r, "«Расчёт готов → черновик КП директору»", async () => { await page.getByRole("button", { name: /Расчёт готов/ }).click(); await page.waitForTimeout(3500); });
  await settle(page);
  out("после", await txt(page), 500);
  r.save();
};

// e2. Директор: «Вернуть на доработку» с комментарием (QUOTE — номер КП в списке)
scenarios.e2 = async (browser) => {
  const r = new Report("e2");
  const who = PEOPLE.director;
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email));
  await spaGoto(page, "/eds/drafts");
  await settle(page);
  out("список КП", await txt(page), 800);
  await page.getByRole("row", { name: new RegExp(process.env.QUOTE ?? "КП-2026-00002") }).getByRole("link", { name: "Открыть" }).click();
  await page.getByText("Чек-лист одобрения").first().waitFor({ timeout: 20000 });
  await settle(page);
  const panel = page.locator(PANEL);
  await panel.getByLabel("Комментарий").fill("Цена шпал выше рынка: пересчитайте у второго поставщика и добавьте срок поставки.");
  await step(page, r, "директор возвращает КП на доработку с комментарием", async () => {
    await panel.getByRole("button", { name: "Вернуть на доработку" }).click();
    await page.waitForTimeout(3500);
  });
  await settle(page);
  out("карточка после возврата", await txt(page), 700);
  out("панель после возврата", await txt(page, PANEL), 700);
  await screen(page, r, "quote-returned-director", { narrow: true });
  r.save();
};

// e3. Директор одобряет КП (Telegram и кабинет)
scenarios.e3 = async (browser) => {
  const r = new Report("e3");
  const who = PEOPLE.director;
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email));
  await spaGoto(page, "/eds/drafts");
  await settle(page);
  await page.getByRole("row", { name: new RegExp(process.env.QUOTE ?? "КП-2026-00002") }).getByRole("link", { name: "Открыть" }).click();
  await page.getByText("Чек-лист одобрения").first().waitFor({ timeout: 20000 });
  await settle(page);
  const panel = page.locator(PANEL);
  for (const ch of ["Telegram-бот", "Кабинет"]) await panel.getByRole("checkbox", { name: new RegExp(ch) }).check().catch(() => {});
  await step(page, r, "директор одобряет КП (версия 2)", async () => { await panel.getByRole("button", { name: /Одобрить КП/ }).click(); await page.waitForTimeout(6000); });
  await settle(page);
  out("карточка", await txt(page), 500);
  r.save();
};

// cab10. Клиент отклоняет КП с причиной (REASON)
scenarios.cab10 = async (browser) => {
  const { cabPage } = await import("./sc-cab.mjs");
  const r = new Report("cab10");
  const { page } = await cabPage(browser, r);
  await page.goto("/quotes");
  await settle(page);
  out("КП клиента", await txt(page, "main"), 700);
  await page.getByRole("link", { name: new RegExp(process.env.QUOTE ?? "КП-2026-00002") }).first().click();
  await settle(page);
  await page.getByRole("button", { name: "Отклонить" }).first().click();
  await page.waitForTimeout(1000);
  out("диалог", await txt(page, "[role=dialog]"), 800);
  await shot(page, r, "cabinet-quote-reject-dialog");
  await step(page, r, "клиент отклоняет КП с причиной", async () => {
    const dlg = page.getByRole("dialog");
    await dlg.getByRole("textbox").first().fill(process.env.REASON ?? "Цена выше предложения конкурента, просим пересчитать.");
    await dlg.getByRole("button", { name: /Отклонить/ }).last().click();
    await page.waitForTimeout(3500);
  });
  await settle(page);
  out("после", await txt(page, "main"), 900);
  await screen(page, r, "cabinet-quote-rejected", { narrow: true });
  r.save();
};

// qv. Карточка КП директора: отчёт «Отправка клиенту» (QUOTE)
scenarios.qv = async (browser) => {
  const r = new Report("qv");
  const { page } = await np(browser);
  await signIn(page, r, PEOPLE.director.email, pwOf(PEOPLE.director.email));
  await spaGoto(page, "/eds/drafts");
  await settle(page);
  await page.getByRole("tab", { name: "Все КП" }).click().catch(() => {});
  await page.waitForTimeout(1000);
  await page.getByRole("row", { name: new RegExp(process.env.QUOTE ?? "КП-2026-00002") }).getByRole("link", { name: "Открыть" }).first().click();
  await settle(page);
  out("карточка КП", await txt(page), 3000); out("панель", await txt(page, PANEL), 1500); await shot(page, r, "quote2-director-card");
  r.save();
};

// e4. Расчёт ЗВ (DEAL) с позицией из каталога: сопоставить, ЗАРЕЗЕРВИРОВАТЬ ДО «Расчёт готов», цены, виза, «Расчёт готов»
scenarios.e4 = async (browser) => {
  const r = new Report("e4");
  const mu = PEOPLE.manager_all;
  const deal = process.env.DEAL;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, `/erp/calc/${encodeURIComponent(deal)}`);
  await settle(page);
  await page.getByRole("button", { name: "Начать расчёт" }).click().catch(() => {});
  await page.waitForTimeout(1500);
  await step(page, r, "строка «Рельс Р65» 10000 кг", async () => {
    await page.getByRole("button", { name: "Добавить строку" }).first().click();
    const dlg = page.getByRole("dialog");
    await dlg.getByLabel("Наименование").fill("Рельс Р65 ГОСТ Р 51685");
    await dlg.getByLabel("Количество").fill("10000");
    await dlg.getByLabel("Единица").fill("кг");
    await dlg.getByRole("button", { name: "Добавить", exact: true }).click();
    await page.waitForTimeout(1500);
  });
  const row = page.locator("table tbody tr").first();
  await step(page, r, "сопоставление с каталогом", async () => {
    await row.getByRole("button", { name: /Сопоставить/ }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Выбрать" }).first().click();
    await page.waitForTimeout(2500);
  });
  await step(page, r, "резерв со склада ДО «Расчёт готов»", async () => {
    await page.getByRole("button", { name: /Зарезервировать/ }).first().click();
    await page.waitForTimeout(2500);
  });
  await settle(page);
  out("строка после резерва", await txt(page), 1700);
  const fillNum = async (loc, v) => { await loc.fill(v); await loc.blur(); await page.waitForTimeout(800); };
  await fillNum(row.getByLabel(/^Цена клиенту/), "4200");
  await step(page, r, "виза и «Расчёт готов»", async () => {
    await row.getByRole("button", { name: /Подтвердить/ }).click();
    await page.waitForTimeout(1500);
    await page.getByRole("button", { name: /Расчёт готов/ }).click();
    await page.waitForTimeout(3500);
  });
  r.save();
};

// n1. Служебка с суммой: МУ создаёт -> директор «Согласовать» -> у МУ (бухгалтерия) строка «Оплатить в Счета и оплаты» (B-D24-5)
scenarios.n1 = async (browser) => {
  const r = new Report("n1");
  const mu = PEOPLE.manager_all, dir = PEOPLE.director;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, "/eds/new");
  await settle(page);
  await step(page, r, "МУ отправляет служебку на оплату (1 200 000 сум)", async () => {
    await page.getByLabel("Тема").fill("Оплата аренды склада за ноябрь (D2-6)");
    await page.getByLabel("Текст").fill("Прошу согласовать оплату аренды склада за ноябрь. Данные вымышленные.");
    await page.getByLabel("Сумма, сум").fill("1200000");
    await page.getByRole("button", { name: "Отправить на согласование" }).click();
    await page.waitForURL((u) => !/\/eds\/new/.test(String(u)), { timeout: 60000, waitUntil: "commit" });
    await settle(page);
  });
  const memoUrl = page.url();
  console.log("URL служебки", memoUrl);
  const { page: pd } = await np(browser);
  await signIn(pd, r, dir.email, pwOf(dir.email));
  await spaGoto(pd, "/eds/approvals");
  await settle(pd);
  await pd.getByRole("link", { name: "Открыть" }).first().click();
  await settle(pd);
  await step(pd, r, "директор согласовывает служебку", async () => {
    await pd.locator(PANEL).getByRole("button", { name: "Согласовать" }).click();
    await pd.waitForTimeout(3500);
  });
  out("директор после", await txt(pd, PANEL), 500);
  r.save();
};

// n2. МУ: строка «Оплатить» -> Счета и оплаты · Служебки к оплате -> «Принять к оплате» / «Оплатить»
scenarios.n2 = async (browser) => {
  const r = new Report("n2");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await settle(page);
  out("очередь", await txt(page), 1200);
  await screen(page, r, "queue-pay-memo", { narrow: true });
  await step(page, r, "строка очереди ведёт в «Счета и оплаты»", async () => {
    await page.getByRole("link", { name: /Открыть|Оплатить/ }).first().click();
    await settle(page);
  });
  console.log("URL", page.url());
  out("экран", await txt(page), 1500);
  out("панель", await txt(page, PANEL), 1800);
  await screen(page, r, "memo-pay-screen", { narrow: true });
  r.save();
};

// n3. Бухгалтер: «Оплатить в Счета и оплаты» -> «Оплачено» (дата, сумма, платёжное поручение)
scenarios.n3 = async (browser) => {
  const r = new Report("n3");
  const who = PEOPLE.accountant;
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email));
  await spaGoto(page, "/eds/approvals/%D0%A1%D0%97-2026%2F001?panel=open&tab=agree");
  await settle(page);
  await step(page, r, "бухгалтер: «Оплатить в Счета и оплаты»", async () => {
    await page.locator(PANEL).getByRole("link", { name: /Оплатить в/ }).or(page.locator(PANEL).getByRole("button", { name: /Оплатить в/ })).first().click();
    await page.waitForURL(/eds\/payments/, { timeout: 20000, waitUntil: "commit" });
    await settle(page);
  });
  console.log("URL", page.url());
  out("экран", await txt(page), 900);
  out("панель", await txt(page, PANEL), 2200);
  await screen(page, r, "memo-pay-screen", { narrow: false });
  const panel = page.locator(PANEL);
  const sum = panel.getByLabel(/Сумма оплаты/);
  if (!(await sum.inputValue().catch(() => ""))) { await sum.fill("1200000"); await sum.blur(); }
  await panel.locator('input[type="file"]').first().setInputFiles(`${process.env.QA_OUT}/demo/payment-proof.pdf`);
  await step(page, r, "бухгалтер отмечает «Оплачено»", async () => {
    await panel.getByRole("button", { name: "Оплачено" }).click();
    await page.waitForTimeout(3500);
  });
  await settle(page);
  out("после «Оплачено»", await txt(page, PANEL), 800);
  out("экран", await txt(page), 600);
  await shot(page, r, "memo-paid");
  r.save();
};

// r1. P8b: делопроизводитель регистрирует требование ГНК -> «Ждёт резолюции» у директора
scenarios.r1 = async (browser) => {
  const r = new Report("r1");
  const reg = PEOPLE.registrar;
  const { page } = await np(browser);
  await signIn(page, r, reg.email, pwOf(reg.email));
  await spaGoto(page, "/eds/register");
  await settle(page);
  const pickOpt = async (label, pat) => {
    await page.getByLabel(label, { exact: true }).click();
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option", { hasText: pat }).first().click();
  };
  await pickOpt("Вид документа", /Требование|ГНК|налог/i);
  await page.getByLabel("Корреспондент", { exact: true }).fill("Государственный налоговый комитет (демо)");
  await page.getByLabel("ИНН корреспондента").fill("201122334");
  await page.getByLabel("Исходящий номер отправителя").fill("12/345");
  await page.getByLabel("Тема").fill("Требование о представлении документов по проверке (демо D2-6)");
  await page.getByLabel("Краткое содержание").fill("Представить договоры и акты за III квартал 2026. Данные вымышленные.");
  await page.locator('input[type="file"]').first().setInputFiles(`${process.env.QA_OUT}/demo/scan-contract.pdf`);
  await page.waitForTimeout(2000);
  await step(page, r, "делопроизводитель регистрирует требование ГНК", async () => {
    await page.getByRole("button", { name: /Зарегистрировать/ }).last().click();
    await page.waitForTimeout(4000);
  });
  await settle(page);
  out("после регистрации", await txt(page), 700);
  await screen(page, r, "register-done", { narrow: true });
  r.save();
};

// r2. P8b: директор накладывает резолюцию-поручение (исполнитель — МУ) на ВХ (LETTER)
scenarios.r2 = async (browser) => {
  const r = new Report("r2");
  const who = PEOPLE.director;
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email));
  await spaGoto(page, `/eds/inbox/${encodeURIComponent(process.env.LETTER)}?panel=open&tab=resolution`);
  await settle(page);
  out("панель резолюции", await txt(page, PANEL), 2500);
  await shot(page, r, "gnk-resolution-form");
  r.save();
};

// r3. P8b: директор -> «К исполнению», ответственный МУ; затем МУ: строка «Моих задач» -> «Исполнено»
scenarios.r3 = async (browser) => {
  const r = new Report("r3");
  const who = PEOPLE.director, mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email));
  await spaGoto(page, `/eds/inbox/${encodeURIComponent(process.env.LETTER)}?panel=open&tab=resolution`);
  await settle(page);
  const panel = page.locator(PANEL);
  await step(page, r, "директор: ответственный — МУ, «Наложить резолюцию»", async () => {
    await panel.getByLabel("Ответственный").click();
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option", { hasText: mu.name }).first().click();
    await shot(page, r, "gnk-resolution-filled");
    await panel.getByRole("button", { name: "Наложить резолюцию" }).click();
    await page.waitForTimeout(3500);
  });
  await settle(page);
  out("письмо после резолюции", await txt(page), 1200);
  await screen(page, r, "gnk-resolution-done", { narrow: true });
  const { page: pm } = await np(browser);
  await signIn(pm, r, mu.email, pwOf(mu.email));
  await settle(pm);
  out("очередь МУ", await txt(pm), 1200);
  await screen(pm, r, "gnk-queue-mu", { narrow: true });
  await step(pm, r, "строка поручения ведёт на письмо", async () => {
    await pm.getByRole("link", { name: /Открыть/ }).first().click();
    await pm.waitForURL(/eds\/inbox/, { timeout: 20000, waitUntil: "commit" });
    await settle(pm);
  });
  out("панель поручения", await txt(pm, PANEL), 2200);
  await shot(pm, r, "gnk-instruction-panel");
  r.save();
};

// r4. P8b: МУ «Исполнено» с отчётом; директор видит письмо «Исполнено»
scenarios.r4 = async (browser) => {
  const r = new Report("r4");
  const mu = PEOPLE.manager_all, dir = PEOPLE.director;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await settle(page);
  await page.getByRole("link", { name: /Открыть/ }).first().click();
  await page.waitForURL(/eds\/tasks/, { timeout: 20000, waitUntil: "commit" });
  await settle(page);
  await page.getByRole("textbox", { name: "Отчёт" }).fill("Договоры и акты за III квартал подготовлены и переданы в налоговую (демо).");
  await step(page, r, "МУ нажимает «Исполнено»", async () => {
    await page.getByRole("button", { name: "Исполнено" }).first().click();
    await page.waitForTimeout(3500);
  });
  await settle(page);
  out("после «Исполнено»", await txt(page), 800);
  await screen(page, r, "gnk-done-mu", { narrow: true });
  const { page: pd } = await np(browser);
  await signIn(pd, r, dir.email, pwOf(dir.email));
  await spaGoto(pd, `/eds/inbox/${encodeURIComponent(process.env.LETTER)}`);
  await settle(pd);
  out("письмо у директора", (await txt(pd)).slice(0, 300), 300);
  r.check("письмо в статусе «Исполнено»", /Исполнено/.test(await txt(pd)));
  await screen(pd, r, "gnk-done-director", { narrow: false });
  r.save();
};

// sweep. Итоговый проход axe + горизонтальная прокрутка по ключевым экранам D2 (1440 и 390)
scenarios.sweep = async (browser) => {
  const r = new Report("sweep");
  const PRJ = "/eds/projects/%D0%9F%D0%A0-2026-001";
  const plan = {
    manager_all: [
      ["queue", "/dashboard/queue"],
      ["calc-list", "/erp/requests"],
      ["calc-zv1", "/erp/calc/%D0%97%D0%92-2026-001"],
      ["calc-zv3", "/erp/calc/%D0%97%D0%92-2026-003"],
      ["stock", "/erp/stock"],
      ["catalog", "/erp/catalog"],
      ["projects", "/eds/projects"],
      ["project-card", PRJ],
      ["project-act-panel", PRJ + "?panel=open&tab=act"],
      ["payments", "/eds/payments"],
      ["invoice", "/eds/payments/1"],
      ["invoice-panel", "/eds/payments/1?panel=open&tab=payment"],
      ["documents", "/eds/documents"],
    ],
    director: [
      ["queue", "/dashboard/queue"],
      ["drafts", "/eds/drafts"],
      ["inbox", "/eds/inbox"],
      ["letter-gnk", "/eds/inbox/" + encodeURIComponent("ВХ-004/26")],
      ["quote-approved", "/eds/drafts"],
    ],
    registrar: [["messages", "/crm/messages"], ["leads", "/crm/leads"]],
    admin: [["setup", "/admin/setup"], ["company", "/admin/company"]],
  };
  for (const [key, list] of Object.entries(plan)) {
    for (const w of [1440, 390]) {
      const { page, ctx } = await np(browser, w);
      const who = key === "admin" ? { email: state().adminEmail } : PEOPLE[key];
      await signIn(page, r, who.email, key === "admin" ? state().adminPw : pwOf(who.email));
      for (const [name, path] of list) {
        await spaGoto(page, path);
        await settle(page);
        await screenHere(page, r, `${key}-${name}`);
      }
      await ctx.close();
    }
  }
  r.save();
};

// ax2. axe в открытых формах: «Новый заказ поставщику», «Оприходовать или списать», «Добавить позицию», «Сопоставить с каталогом»
scenarios.ax2 = async (browser) => {
  const r = new Report("ax2");
  const { page } = await np(browser);
  await signIn(page, r, PEOPLE.manager_all.email, pwOf(PEOPLE.manager_all.email));
  await spaGoto(page, "/erp/stock");
  await settle(page);
  await page.getByRole("tab", { name: "Заказы поставщикам" }).click();
  await page.getByRole("button", { name: "Создать заказ" }).first().click();
  await page.waitForTimeout(800);
  await screenHere(page, r, "order-create-dialog");
  await page.keyboard.press("Escape");
  await spaGoto(page, "/erp/catalog");
  await settle(page);
  await page.getByRole("button", { name: "Добавить позицию" }).first().click();
  await page.waitForTimeout(800);
  await screenHere(page, r, "catalog-add-dialog");
  r.save();
};

// z4. Сквозной остаток на проекте 4: счёт выставить, оплату подтвердить по выписке (без платёжки клиента), акт выпустить, скан акта -> «Выполнено»
scenarios.z4 = async (browser) => {
  const r = new Report("z4");
  const mu = PEOPLE.manager_all;
  const inv = process.env.INV ?? "2";
  const prj = `/eds/projects/${encodeURIComponent(process.env.PRJ ?? "ПР-2026-004")}`;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, `/eds/payments/${inv}?panel=open&tab=payment`);
  await settle(page);
  const panel = page.locator(PANEL);
  await step(page, r, "МУ выставляет счёт проекта 4", async () => { await panel.getByRole("button", { name: "Выставить счёт" }).click(); await page.waitForTimeout(4000); });
  await settle(page);
  const sum = panel.getByLabel("Сумма по выписке");
  const rest = await sum.inputValue();
  console.log("остаток в поле:", rest);
  await step(page, r, "МУ подтверждает оплату по выписке (платёжки клиента нет)", async () => {
    await panel.getByRole("button", { name: "Подтвердить оплату" }).click();
    await page.waitForTimeout(4000);
  });
  await settle(page);
  out("счёт", (await txt(page)).slice(0, 200), 200);
  await spaGoto(page, prj + "?panel=open&tab=act");
  await settle(page);
  await step(page, r, "МУ выпускает акт", async () => { await page.locator(PANEL).getByRole("button", { name: /Выпустить акт/ }).click(); await page.waitForTimeout(4000); });
  await settle(page);
  await step(page, r, "МУ прикрепляет скан акта -> «Подписан»", async () => {
    await page.locator(PANEL).locator('input[type="file"]').first().setInputFiles(`${process.env.QA_OUT}/demo/scan-act.pdf`);
    await page.waitForTimeout(1200);
    await shot(page, r, "act-scan-attached");
    await page.locator(PANEL).getByRole("button", { name: /Прикрепить скан/ }).click();
    await page.waitForTimeout(4000);
  });
  await settle(page);
  out("панель акта", await txt(page, PANEL), 700);
  out("проект", (await txt(page)).slice(0, 700), 700);
  await screen(page, r, "project4-done", { narrow: true });
  r.save();
};
