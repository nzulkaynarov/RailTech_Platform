import { screenHere, ADMIN, PEOPLE, PANEL, Report, bff, compose, np, pwOf, saveState, screen, secret, settle, shot, signIn, spaGoto, state, step, toastsGone } from "./common.mjs";
import { inject, injectCb } from "./sc-base.mjs";
export const scenarios = {};
const txt = async (page, sel = "#main-content") => (await page.locator(sel).first().innerText().catch(() => "")).replace(/\n{2,}/g, "\n");
const out = (label, t, n = 1200) => console.log(`--- ${label}\n${String(t).slice(0, n)}`);

// h1. D17G-1: делопроизводитель передаёт лида менеджеру-универсалу (с запиской); МУ видит его в «Моих задачах»
scenarios.h1 = async (browser) => {
  const r = new Report("h1");
  const reg = PEOPLE.registrar, mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, reg.email, pwOf(reg.email));
  await spaGoto(page, "/crm/messages?lead=L-0001&panel=open");
  await settle(page);
  r.check("у делопроизводителя нет «Забрать» и поля ответа клиенту", (await page.getByRole("button", { name: /^Забрать/ }).count()) === 0 && (await page.getByLabel(/^Сообщение клиенту/).count()) === 0);
  await step(page, r, "ДП: «Передать менеджеру» с запиской", async () => {
    await page.getByRole("button", { name: "Передать менеджеру" }).first().click();
    const panel = page.getByRole("dialog");
    await panel.getByLabel("Записка менеджеру").fill("Клиент просит КП: рельсы Р65 40 т и доставка до станции Ташкент-Товарный до 20 ноября.");
    await panel.getByRole("combobox").first().click();
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option", { hasText: "Демо Универсалов" }).first().click();
    await shot(page, r, "handoff-form-filled");
    await panel.getByRole("button", { name: "Передать", exact: true }).click();
    await page.waitForTimeout(3000);
  });
  await settle(page);
  out("ДП после передачи", await txt(page, "body"), 1500);
  await screen(page, r, "handoff-done-registrar", { narrow: true });
  const { page: pm } = await np(browser);
  await signIn(pm, r, mu.email, pwOf(mu.email));
  await settle(pm);
  out("МУ очередь", await txt(pm), 1500);
  await screen(pm, r, "handoff-mu-queue", { narrow: true });
  r.save();
};

// m1. МУ забирает лида из передачи, отвечает клиенту в Telegram, создаёт заявку (двойной клик -> одна ЗВ), клиент с e-mail
scenarios.m1 = async (browser) => {
  const r = new Report("m1");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  await step(page, r, "МУ открывает строку «Новый лид от делопроизводителя» из «Моих задач»", async () => {
    await page.getByRole("link", { name: "Открыть" }).first().click();
    await page.waitForURL(/crm\/messages/, { timeout: 20000, waitUntil: "commit" });
    await settle(page);
  });
  await step(page, r, "МУ забирает лида", async () => {
    await page.getByRole("button", { name: /Забрать/ }).first().click();
    await page.waitForTimeout(2500);
  });
  await step(page, r, "МУ отвечает клиенту в Telegram", async () => {
    await page.getByLabel(/^(Сообщение клиенту|Заметка для команды)$/).fill("Здравствуйте, Азиз! Принял ваш запрос, оформляю заявку — КП пришлю в течение рабочего дня.");
    await page.getByRole("button", { name: "Отправить" }).click();
    await page.locator(".pf-msg-bubble", { hasText: "Принял ваш запрос" }).first().waitFor({ timeout: 15000 });
  });
  await settle(page);
  await screen(page, r, "mu-reply-sent", { narrow: true });
  await spaGoto(page, `/crm/leads?lead=L-0001&create=1&panel=open&tab=card`);
  await settle(page);
  const panel = page.locator(PANEL);
  const posts = [];
  page.on("request", (q) => { if (q.method() === "POST" && /crm\/requests/.test(q.url())) posts.push(q.url()); });
  await panel.getByLabel("Название компании").fill("ООО Демо Путь");
  await panel.getByLabel("ИНН").fill("301234567");
  await panel.getByRole("textbox", { name: "Имя", exact: true }).fill("Азиз Каримов");
  await panel.getByLabel("Почта").fill("aziz.client.d26@demo.example");
  await panel.getByLabel("Суть запроса").fill("Рельсы Р65, 40 т, и доставка до станции Ташкент-Товарный до 20 ноября (демо гейта D2-6)");
  await screen(page, r, "create-request-form", { narrow: false });
  await panel.getByRole("button", { name: /^Создать заявку/ }).dblclick({ delay: 10 });
  await page.waitForTimeout(7000);
  await settle(page);
  r.check("двойной клик: один POST /crm/requests", posts.length === 1, `POST: ${posts.length}`);
  out("панель после создания", await txt(page, PANEL), 1500);
  await screen(page, r, "create-request-done", { narrow: true });
  r.save();
};

// d1. Директор: «Моя очередь» -> резолюция на ВХ (оба исполнителя — МУ); номер ЗВ открывает рабочую карточку (B-UIA-1)
scenarios.d1 = async (browser) => {
  const r = new Report("d1");
  const who = PEOPLE.director, mu = PEOPLE.manager_all;
  const letter = process.env.LETTER ?? "ВХ-001/26";
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email));
  await settle(page);
  out("очередь директора", await txt(page), 1200);
  await screen(page, r, "director-queue-resolve", { narrow: true });
  await step(page, r, "строка очереди ведёт на письмо", async () => {
    await page.getByRole("link", { name: /Открыть/ }).first().click();
    await page.waitForURL(/eds\/inbox/, { timeout: 20000, waitUntil: "commit" });
    await settle(page);
  });
  const panel = page.locator(PANEL);
  await panel.getByLabel("Текст резолюции").fill("Рассчитать поставку Р65 40 т и услугу доставки, КП до пятницы.");
  const combos = panel.getByRole("combobox");
  for (const i of [0, 1]) {
    await combos.nth(i).click();
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option", { hasText: mu.name }).first().click();
  }
  await panel.getByLabel("Маржа не ниже, %").fill("10");
  await screen(page, r, "resolution-filled", { narrow: false });
  await step(page, r, "директор утверждает резолюцию", async () => {
    await panel.getByRole("button", { name: /Утвердить резолюцию/ }).click();
    await page.getByText(/Резолюция наложена/).first().waitFor({ timeout: 20000 });
  });
  await settle(page);
  out("после резолюции", await txt(page), 1500);
  await screen(page, r, "resolution-done", { narrow: true });
  // номер ЗВ открывает рабочую карточку (B-UIA-1)
  const zv = page.getByRole("link", { name: /ЗВ-2026-001/ }).first();
  r.check("в письме номер ЗВ — ссылка", (await zv.count()) > 0);
  if (await zv.count()) {
    await zv.click();
    await settle(page);
    out(`ЗВ -> ${page.url()}`, await txt(page), 800);
    await screen(page, r, "zv-card-from-letter", { narrow: true });
  }
  r.save();
};

// p1. Подготовка справочников (МУ): позиция «Рельс Р65» с предложением поставщика и 15 т на складе (резерв и дефицит при принятии КП)
scenarios.p1 = async (browser) => {
  const r = new Report("p1");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, "/erp/catalog");
  await settle(page);
  await step(page, r, "МУ добавляет позицию «Рельс Р65 ГОСТ Р 51685»", async () => {
    await page.getByRole("button", { name: "Добавить позицию" }).first().click();
    const dlg = page.getByRole("dialog");
    await dlg.getByLabel("Название").fill("Рельс Р65 ГОСТ Р 51685");
    await dlg.getByLabel("Единица измерения").click();
    console.log("UNITS", JSON.stringify(await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option").allInnerTexts()));
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option", { hasText: /^кг$/ }).first().click();
    await dlg.getByRole("button", { name: "Добавить", exact: true }).click();
    await page.waitForTimeout(2500);
  });
  await settle(page);
  out("каталог", await txt(page), 800);
  await shot(page, r, "catalog-after-add");
  await page.getByText("Рельс Р65 ГОСТ Р 51685").first().click().catch(() => {});
  await page.waitForTimeout(1500);
  out("панель позиции", await txt(page, PANEL), 2500);
  await shot(page, r, "catalog-item-panel");
  r.save();
};

// p2. Склад: МУ ищет позицию и оприходовывает остаток (ручной ввод)
scenarios.p2 = async (browser) => {
  const r = new Report("p2");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, "/erp/stock");
  await settle(page);
  const search = page.getByRole("searchbox").first().or(page.getByPlaceholder(/Найти товар/)).first();
  await search.fill("Рельс");
  await search.press("Enter");
  await page.waitForTimeout(2000);
  out("поиск", await txt(page), 600);
  await shot(page, r, "stock-search-result");
  await page.getByRole("button", { name: /Рельс Р65/ }).first().click().catch((e) => console.log("клик по позиции:", String(e.message).split("\n")[0]));
  await page.waitForTimeout(1500);
  out("карточка остатка", await txt(page, "body"), 2500);
  await shot(page, r, "stock-product-drawer");
  r.save();
};

// p3. Склад: оприходовать 15000 кг
scenarios.p3 = async (browser) => {
  const r = new Report("p3");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, "/erp/stock");
  await settle(page);
  const search = page.getByPlaceholder(/Найти товар/).first();
  await search.fill("Рельс");
  await search.press("Enter");
  await page.waitForTimeout(1500);
  await page.getByRole("button", { name: /Рельс Р65/ }).first().click();
  await page.waitForTimeout(1000);
  await page.getByRole("button", { name: /Оприходовать или списать/ }).click();
  await page.waitForTimeout(800);
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Количество").fill("15000");
  await dlg.getByLabel("Ячейка").fill("А-1");
  await dlg.getByLabel("Основание").fill("Ручной ввод остатка для демо D2-6");
  await shot(page, r, "stock-adjust-form");
  await step(page, r, "МУ оприходовал 15000 кг", async () => {
    await dlg.getByRole("button", { name: "Записать" }).click();
    await page.getByText(/15\s?000/).first().waitFor({ timeout: 15000 });
  });
  await page.waitForTimeout(1000);
  out("после", await txt(page, "body"), 1200);
  await shot(page, r, "stock-after-adjust");
  r.save();
};

// k1. МУ: строки расчёта (товар и услуга), сопоставление с каталогом, резерв со склада
scenarios.k1 = async (browser) => {
  const r = new Report("k1");
  const mu = PEOPLE.manager_all;
  const deal = process.env.DEAL ?? "ЗВ-2026-001";
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, `/erp/calc/${encodeURIComponent(deal)}`);
  await settle(page);
  for (const [name, qty, unit, svc] of [["Рельс Р65 ГОСТ Р 51685", "40000", "кг", false], ["Доставка до станции Ташкент-Товарный", "1", "рейс", true]]) {
    await step(page, r, `МУ добавляет строку «${name}»`, async () => {
      await page.getByRole("button", { name: "Добавить строку" }).first().click();
      const dlg = page.getByRole("dialog");
      await dlg.getByLabel("Наименование").fill(name);
      await dlg.getByLabel("Количество").fill(qty);
      await dlg.getByLabel("Единица").fill(unit);
      if (svc) await dlg.getByRole("radio", { name: "Услуга" }).check();
      await dlg.getByRole("button", { name: "Добавить", exact: true }).click();
      await page.waitForTimeout(1500);
    });
  }
  await settle(page);
  out("расчёт", await txt(page), 3500);
  await screen(page, r, "calc-lines", { narrow: false });
  r.save();
};

// k1b. Сопоставление строки товара с каталогом (поставщик и срок подтягиваются) и резерв со склада
scenarios.k1b = async (browser) => {
  const r = new Report("k1b");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, `/erp/calc/${encodeURIComponent(process.env.DEAL ?? "ЗВ-2026-001")}`);
  await settle(page);
  const goods = page.locator("table tbody tr").nth(0);
  await goods.getByRole("button", { name: /Сопоставить/ }).click();
  await page.waitForTimeout(1500);
  await shot(page, r, "calc-map-dialog");
  await step(page, r, "МУ выбирает позицию каталога", async () => {
    await page.getByRole("dialog").getByRole("button", { name: "Выбрать" }).first().click();
    await page.waitForTimeout(2500);
  });
  await settle(page);
  out("строки после сопоставления", await txt(page), 2500);
  await screen(page, r, "calc-mapped", { narrow: false });
  r.save();
};

// k2. МУ: цены, визы обеих зон, «Расчёт готов → черновик КП директору»; строка «Моих задач» меняется
scenarios.k2 = async (browser) => {
  const r = new Report("k2");
  const mu = PEOPLE.manager_all;
  const deal = process.env.DEAL ?? "ЗВ-2026-001";
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, `/erp/calc/${encodeURIComponent(deal)}`);
  await settle(page);
  const rows = page.locator("table tbody tr");
  const goods = rows.nth(0), svc = rows.nth(1);
  const fillNum = async (loc, v) => { await loc.fill(v); await loc.blur(); await page.waitForTimeout(800); };
  await fillNum(goods.getByLabel(/^Цена клиенту/), "4200");
  await fillNum(svc.getByLabel(/^Ставка бригады/), "500000");
  await fillNum(svc.getByLabel(/^Дней работы/), "2");
  await fillNum(svc.getByLabel(/^Цена клиенту/), "1500000");
  await settle(page);
  out("строки с ценами", await txt(page), 2800);
  await screen(page, r, "calc-priced", { narrow: false });
  r.check("«Расчёт готов» неактивна без виз", await page.getByRole("button", { name: /Расчёт готов/ }).isDisabled());
  await step(page, r, "МУ подтверждает визу товара (снабжение)", async () => {
    await goods.getByRole("button", { name: /Подтвердить/ }).click();
    await page.waitForTimeout(1500);
  });
  await step(page, r, "МУ подтверждает визу услуги (гл. инженер)", async () => {
    await svc.getByRole("button", { name: /Подтвердить/ }).click();
    await page.waitForTimeout(1500);
  });
  await settle(page);
  out("после виз", await txt(page), 2800);
  await screen(page, r, "calc-visas", { narrow: false });
  await step(page, r, "«Расчёт готов → черновик КП директору»", async () => {
    await page.getByRole("button", { name: /Расчёт готов/ }).click();
    await page.waitForTimeout(3500);
  });
  await settle(page);
  out("после «Расчёт готов»", await txt(page), 1200);
  await screen(page, r, "calc-sent", { narrow: true });
  r.save();
};

// q1. Директор: очередь -> КП на одобрение -> каналы -> «Одобрить КП» -> отчёт по каналам в карточке (D17G-2)
scenarios.q1 = async (browser) => {
  const r = new Report("q1");
  const who = PEOPLE.director;
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email));
  await settle(page);
  out("очередь директора", await txt(page), 1200);
  await screen(page, r, "director-queue-quote", { narrow: true });
  const rowsInQueue = await page.getByRole("link", { name: /Открыть/ }).count();
  r.check("в «Моих задачах» директора есть строка «Одобрить КП»", rowsInQueue > 0, `строк «Открыть»: ${rowsInQueue}`);
  if (!rowsInQueue) await spaGoto(page, "/eds/drafts");
  await settle(page);
  await step(page, r, "КП открывается (из строки очереди или из списка)", async () => {
    await page.getByRole("link", { name: /Открыть/ }).first().click();
    await page.getByText("Чек-лист одобрения").first().waitFor({ timeout: 20000 });
  });
  await settle(page);
  const panel = page.locator(PANEL);
  out("карточка КП", await txt(page), 1800);
  out("панель одобрения", await txt(page, PANEL), 2500);
  await screen(page, r, "quote-approve-before", { narrow: false });
  const bell = await page.getByRole("button", { name: /уведомлен/i }).first().innerText().catch(() => "");
  console.log("колокольчик директора:", bell);
  for (const ch of ["Telegram-бот", "Кабинет"]) await panel.getByRole("checkbox", { name: new RegExp(ch) }).check().catch((e) => console.log("канал", ch, String(e.message).split("\n")[0]));
  const t0 = Date.now();
  await step(page, r, "директор одобряет КП (Telegram и кабинет)", async () => {
    await panel.getByRole("button", { name: /Одобрить КП/ }).click();
    await page.waitForTimeout(6000);
  });
  await settle(page);
  r.note("одобрение -> экран, мс", String(Date.now() - t0));
  out("карточка после одобрения", await txt(page), 3000);
  out("панель после одобрения", await txt(page, PANEL), 2000);
  await screen(page, r, "quote-approved", { narrow: true });
  r.save();
};

// bell. Колокольчик и «Мои задачи» выбранной роли: что пришло (ROLE=manager_all)
scenarios.bell = async (browser) => {
  const key = process.env.ROLE ?? "manager_all";
  const who = PEOPLE[key];
  const r = new Report(`bell-${key}`);
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email));
  await spaGoto(page, process.env.PATH_ ?? "/dashboard/queue");
  await settle(page);
  out("очередь", await txt(page), 2200);
  await screen(page, r, process.env.TAG ?? "queue", { narrow: !!process.env.NARROW });
  await page.getByRole("button", { name: /уведомлен/i }).first().click().catch((e) => console.log("колокольчик:", String(e.message).split("\n")[0]));
  await page.waitForTimeout(1500);
  out("колокольчик", await txt(page, "[role=dialog], .ant-popover, .ant-drawer, #pf-context-panel"), 2500);
  await shot(page, r, `${process.env.TAG ?? "queue"}-bell`);
  r.save();
};

const PROJ = process.env.PRJ ? `/eds/projects/${encodeURIComponent(process.env.PRJ)}` : "/eds/projects/%D0%9F%D0%A0-2026-001";
const DEMO = () => `${process.env.QA_OUT}/demo`;

// ct1. МУ: договор «выставлен у оператора» -> строка «договор ждёт скана» -> скан -> «Подписан»
scenarios.ct1 = async (browser) => {
  const r = new Report("ct1");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await settle(page);
  await step(page, r, "строка «Выставить у оператора договор» ведёт в проект", async () => {
    await page.getByRole("link", { name: /Открыть/ }).first().click();
    await page.waitForURL(/eds\/projects/, { timeout: 20000, waitUntil: "commit" });
    await settle(page);
  });
  const panel = page.locator(PANEL);
  await panel.getByLabel(/Оператор или номер/).fill("Демо-оператор ЭДО № 5501");
  await shot(page, r, "contract-issue-form");
  await step(page, r, "МУ: «Отметить: выставлен у оператора»", async () => {
    await panel.getByRole("button", { name: /Отметить: выставлен у оператора/ }).click();
    await page.waitForTimeout(3000);
  });
  await settle(page);
  out("панель договора", await txt(page, PANEL), 2200);
  await screen(page, r, "contract-issued", { narrow: false });
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  out("очередь", await txt(page), 1200);
  await screen(page, r, "queue-contract-scan", { narrow: true });
  r.save();
};

// ct2. МУ: скан подписанного договора -> «Подписан»
scenarios.ct2 = async (browser) => {
  const r = new Report("ct2");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, PROJ + "?panel=open&tab=contract");
  await settle(page);
  const panel = page.locator(PANEL);
  out("панель", await txt(page, PANEL), 1600);
  await step(page, r, "МУ прикрепляет скан подписанного договора", async () => {
    await panel.locator('input[type="file"]').first().setInputFiles(`${DEMO()}/scan-contract.pdf`);
    await page.waitForTimeout(1500);
    await shot(page, r, "contract-scan-attached");
    await panel.getByRole("button", { name: /Прикрепить скан|Подписан|Подтвердить/ }).last().click();
    await page.waitForTimeout(4000);
  });
  await settle(page);
  out("панель после скана", await txt(page, PANEL), 2200);
  out("проект", await txt(page), 1800);
  await screen(page, r, "contract-signed", { narrow: true });
  r.save();
};

// i1. МУ: строка «Выставить счёт» -> Счета и оплаты -> «Выставить счёт» -> PDF
scenarios.i1 = async (browser) => {
  const r = new Report("i1");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await settle(page);
  await step(page, r, "строка очереди «Выставить счёт» открывает счёт", async () => {
    await page.getByRole("link", { name: /Открыть/ }).first().click();
    await page.waitForURL(/eds\/payments/, { timeout: 20000, waitUntil: "commit" });
    await settle(page);
  });
  console.log("URL", page.url());
  out("экран", await txt(page), 1500);
  out("панель", await txt(page, PANEL), 2500);
  await screen(page, r, "invoice-to-issue", { narrow: true });
  r.save();
};

// i2. МУ: «Выставить счёт» -> счёт «Выставлен», PDF скачивается
scenarios.i2 = async (browser) => {
  const r = new Report("i2");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, "/eds/payments/1?panel=open&tab=payment");
  await settle(page);
  const panel = page.locator(PANEL);
  await step(page, r, "МУ нажимает «Выставить счёт»", async () => {
    await panel.getByRole("button", { name: "Выставить счёт" }).click();
    await page.waitForTimeout(4000);
  });
  await settle(page);
  out("экран после выставления", await txt(page), 1800);
  out("панель после выставления", await txt(page, PANEL), 1800);
  await screen(page, r, "invoice-issued", { narrow: true });
  r.save();
};

// a2. Администратор: реквизиты компании (расчётный счёт и МФО нужны для первого счёта) — вымышленные
scenarios.a2 = async (browser) => {
  const r = new Report("a2");
  const { page } = await np(browser);
  await signIn(page, r, state().adminEmail, state().adminPw);
  await spaGoto(page, "/admin/company");
  await settle(page);
  await page.getByLabel("ИНН", { exact: true }).fill("300000001");
  await page.getByLabel("Юридический адрес").fill("г. Ташкент, ул. Демонстрационная, 1");
  await page.getByLabel("Расчётный счёт").fill("20208000100000000001");
  await page.getByLabel("МФО банка").fill("00014");
  await page.getByLabel("Телефон").fill("+998 71 000 00 00");
  await page.getByLabel("Почта компании").fill("info.d26@demo.example");
  await step(page, r, "администратор сохраняет реквизиты компании", async () => {
    await page.getByRole("button", { name: /Сохранить/ }).first().click();
    await page.waitForTimeout(3000);
  });
  out("после сохранения", await txt(page, "body"), 600);
  await shot(page, r, "company-requisites");
  r.save();
};

// i3. МУ: PDF счёта из карточки проекта
scenarios.i3 = async (browser) => {
  const r = new Report("i3");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, PROJ);
  await settle(page);
  await step(page, r, "PDF счёта скачивается из карточки проекта", async () => {
    const [dl] = await Promise.all([page.waitForEvent("download", { timeout: 30000 }), page.getByRole("link", { name: /PDF/ }).or(page.getByRole("button", { name: /PDF/ })).first().click()]);
    await dl.saveAs(`${process.env.QA_OUT}/files/invoice.pdf`);
  });
  r.save();
};

// pay1. МУ: строка «Подтвердить оплату» -> счёт, платёжка клиента -> «Частичная оплата» (SUM, по умолчанию 94 920 000)
scenarios.pay1 = async (browser) => {
  const r = new Report("pay1");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await settle(page);
  await step(page, r, "строка очереди «Подтвердить оплату» открывает счёт с платёжкой", async () => {
    await page.getByRole("link", { name: /Открыть/ }).first().click();
    await page.waitForURL(/eds\/payments/, { timeout: 20000, waitUntil: "commit" });
    await settle(page);
  });
  out("счёт", await txt(page), 1600);
  out("панель", await txt(page, PANEL), 2000);
  await screen(page, r, "payment-confirm-screen", { narrow: true });
  const panel = page.locator(PANEL);
  await step(page, r, "МУ скачивает платёжку клиента", async () => {
    const [dl] = await Promise.all([page.waitForEvent("download", { timeout: 20000 }), page.getByRole("link", { name: /payment-proof|Скачать|Открыть файл/ }).or(page.getByRole("button", { name: /payment-proof|Скачать|Открыть файл/ })).first().click()]);
    await dl.saveAs(`${process.env.QA_OUT}/files/proof-seen-by-manager.pdf`);
  });
  const sum = process.env.SUM ?? "94920000";
  const sumField = panel.getByLabel("Сумма по выписке");
  await sumField.click();
  await sumField.fill(sum);
  await sumField.blur();
  await page.waitForTimeout(600);
  console.log("значение поля суммы:", await sumField.inputValue());
  await panel.getByLabel("Номер операции банка").fill(process.env.OPNO ?? "BNK-0001");
  await shot(page, r, "payment-partial-filled");
  await step(page, r, `МУ нажимает «${process.env.BTN ?? "Подтвердить частичную оплату"}»`, async () => {
    await panel.getByRole("button", { name: process.env.BTN ?? "Подтвердить частичную оплату" }).click();
    await page.waitForTimeout(4000);
  });
  await settle(page);
  out("счёт после", await txt(page), 1800);
  out("панель после", await txt(page, PANEL), 1500);
  await screen(page, r, process.env.TAG ?? "payment-partial-done", { narrow: true });
  r.save();
};

// s1. Закупка: «Создать заказ» -> «На дефицит заявки» -> черновик ЗП (МУ)
scenarios.so1 = async (browser) => {
  const r = new Report("so1");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, "/erp/stock");
  await settle(page);
  await page.getByRole("tab", { name: "Заказы поставщикам" }).click();
  await page.waitForTimeout(800);
  await page.getByRole("button", { name: "Создать заказ" }).first().click();
  const dlg = page.getByRole("dialog");
  await dlg.getByRole("combobox").first().click();
  await page.waitForTimeout(600);
  console.log("ПОСТАВЩИКИ:", JSON.stringify(await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option").allInnerTexts()));
  await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option", { hasText: "Демо Металл" }).first().click();
  await dlg.getByRole("radio", { name: "На дефицит заявки" }).check();
  await page.waitForTimeout(800);
  await dlg.getByLabel("Номер заявки или проекта").fill("ПР-2026-001");
  await shot(page, r, "order-create-deficit");
  await step(page, r, "МУ создаёт черновик заказа на дефицит", async () => {
    await dlg.getByRole("button", { name: "Создать черновик" }).click();
    await page.waitForTimeout(3500);
  });
  await settle(page);
  out("после создания", await txt(page), 1500);
  out("панель", await txt(page, PANEL), 800);
  await screen(page, r, "order-draft", { narrow: true });
  r.save();
};

// rs1. Резерв со склада по строке расчёта вручную (SPEC §3.1 ш. 4/6: сам не делается при принятии КП)
scenarios.rs1 = async (browser) => {
  const r = new Report("rs1");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, "/erp/calc/%D0%97%D0%92-2026-001");
  await settle(page);
  await step(page, r, "МУ резервирует 15000 кг со склада", async () => {
    await page.getByRole("button", { name: /Зарезервировать/ }).first().click();
    await page.waitForTimeout(2500);
  });
  await settle(page);
  out("строка после резерва", await txt(page), 1800);
  await shot(page, r, "calc-reserved");
  r.save();
};

// rs2. Тот же резерв: ответ BFF и текст сообщения пользователю
scenarios.rs2 = async (browser) => {
  const r = new Report("rs2");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, "/erp/calc/%D0%97%D0%92-2026-001");
  await settle(page);
  const resp = page.waitForResponse((x) => /reserve/.test(x.url()) && x.request().method() === "PUT");
  await page.getByRole("button", { name: /Зарезервировать/ }).first().click();
  const x = await resp;
  console.log("RESERVE", x.status(), (await x.text()).slice(0, 400));
  await page.waitForTimeout(300);
  console.log("ТОСТ/АЛЕРТ:", JSON.stringify(await page.locator(".ant-message, [role=alert], .ant-notification").allInnerTexts()));
  await shot(page, r, "calc-reserve-error");
  r.save();
};

// so2. Заказ поставщику: отправить, подтвердить, принять (приёмка) — ACT=<текст кнопки>
scenarios.so2 = async (browser) => {
  const r = new Report("so2");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, "/erp/stock");
  await settle(page);
  await page.getByRole("tab", { name: "Заказы поставщикам" }).click();
  await page.waitForTimeout(800);
  await page.getByText("ЗП-2026-001").first().click();
  await settle(page);
  for (const btn of (process.env.BTNS ?? "Отправить поставщику").split(";")) {
    const b = page.getByRole("button", { name: new RegExp(btn) }).first();
    console.log("КНОПКА", btn, "видна:", await b.isVisible().catch(() => false));
    await step(page, r, `нажимаю «${btn}»`, async () => {
      await b.click();
      await page.waitForTimeout(1500);
      const dlg = page.getByRole("dialog");
      if (await dlg.count()) {
        out("диалог", await txt(page, "[role=dialog]"), 1500);
        await shot(page, r, `order-dialog-${btn.replace(/\W+/g, "_")}`);
        const date = dlg.getByLabel(/дата/i).first();
        if (await date.count()) { await date.fill("10.11.2026"); await date.press("Enter"); await page.waitForTimeout(500); }
        const qty = dlg.getByLabel(/Принято|Количество|Принять/).first();
        if ((await qty.count()) && !(await qty.inputValue().catch(() => "x"))) await qty.fill(process.env.QTY ?? "40000");
        const confirm = dlg.getByRole("button", { name: /Отправить|Подтвердить|Принять|Записать|Да/ }).last();
        await confirm.click();
        await page.waitForTimeout(3500);
      }
    });
    await settle(page);
  }
  out("заказ", await txt(page), 1700);
  console.log("ТОСТЫ:", JSON.stringify(await page.locator(".ant-message, [role=alert]").allInnerTexts()));
  await screen(page, r, process.env.TAG ?? "order-after", { narrow: false });
  r.save();
};

// sh1. Отгрузка по проекту: «Новая отгрузка» -> поиск резервов
scenarios.sh1 = async (browser) => {
  const r = new Report("sh1");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, "/erp/stock");
  await settle(page);
  await page.getByRole("tab", { name: "Отгрузки" }).click();
  await page.waitForTimeout(800);
  const inp = page.getByLabel(/Новая отгрузка по проекту|проекта/i).first();
  await inp.fill(process.env.PRJ ?? "ПР-2026-001");
  await page.getByRole("button", { name: "Найти резервы" }).click();
  await page.waitForTimeout(2500);
  out("после поиска резервов", await txt(page), 1500);
  if (process.env.SHIP) {
    await page.getByLabel("Трек-номер").fill("TRK-D26-0001");
    await page.getByLabel("Перевозчик").fill("Демо-перевозчик");
    await step(page, r, "МУ оформляет отгрузку по резерву", async () => {
      await page.getByRole("button", { name: "Отгрузить" }).click();
      await page.waitForTimeout(3500);
    });
    out("после отгрузки", await txt(page), 1200);
  }
  console.log("ТОСТЫ:", JSON.stringify(await page.locator(".ant-message, [role=alert]").allInnerTexts()));
  await screen(page, r, "shipment-find-reserves", { narrow: false });
  r.save();
};

// ac1. МУ: строка «Выпустить акт» -> вкладка «Акт» -> «Выпустить акт»
scenarios.ac1 = async (browser) => {
  const r = new Report("ac1");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await settle(page);
  await step(page, r, "строка очереди «Выпустить акт» открывает проект", async () => {
    await page.getByRole("link", { name: /Открыть/ }).first().click();
    await page.waitForURL(/eds\/projects/, { timeout: 20000, waitUntil: "commit" });
    await settle(page);
  });
  console.log("URL", page.url());
  out("панель", await txt(page, PANEL), 2500);
  await screen(page, r, "act-to-issue-panel", { narrow: false });
  r.save();
};

// ac2. МУ: выпуск акта (ISSUE_BTN)
scenarios.ac2 = async (browser) => {
  const r = new Report("ac2");
  const mu = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, PROJ + "?panel=open&tab=act");
  await settle(page);
  const panel = page.locator(PANEL);
  out("панель", await txt(page, PANEL), 2500);
  await step(page, r, "МУ выпускает акт", async () => {
    await panel.getByRole("button", { name: /Выпустить акт|Выпустить заново|Выпустить/ }).first().click();
    await page.waitForTimeout(4000);
  });
  await settle(page);
  out("панель после", await txt(page, PANEL), 2500);
  out("проект", await txt(page), 1500);
  await screen(page, r, "act-issued", { narrow: true });
  r.save();
};

// lead2. Второй клиент: лид из бота -> «Забрать» МУ -> «Создать заявку» (LEAD, COMPANY, INN, EMAIL, CNAME, NOTE)
scenarios.lead2 = async (browser) => {
  const r = new Report("lead2");
  const mu = PEOPLE.manager_all;
  const lead = process.env.LEAD ?? "L-0002";
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, `/crm/messages?lead=${lead}&panel=open`);
  await settle(page);
  await step(page, r, `МУ забирает лид ${lead}`, async () => {
    await page.getByRole("button", { name: /Забрать/ }).first().click();
    await page.waitForTimeout(2500);
  });
  await spaGoto(page, `/crm/leads?lead=${lead}&create=1&panel=open&tab=card`);
  await settle(page);
  const panel = page.locator(PANEL);
  await panel.getByLabel("Название компании").fill(process.env.COMPANY ?? "ООО Тест Шпалы");
  await panel.getByLabel("ИНН").fill(process.env.INN ?? "302222222");
  await panel.getByRole("textbox", { name: "Имя", exact: true }).fill(process.env.CNAME ?? "Тимур Исматов");
  await panel.getByLabel("Почта").fill(process.env.EMAIL ?? "client2.d26@demo.example");
  await panel.getByLabel("Суть запроса").fill(process.env.NOTE ?? "Шпалы ЖБ, 500 шт, доставка до станции (демо D2-6, второй клиент)");
  await step(page, r, "МУ создаёт заявку", async () => {
    await panel.getByRole("button", { name: /^Создать заявку/ }).click();
    await page.getByText("Заявка создана").first().waitFor({ timeout: 30000 });
  });
  await page.waitForTimeout(3000);
  out("панель", await txt(page, PANEL), 500);
  r.save();
};

// zv. B-UIA-1: где виден номер ЗВ и ведёт ли он в рабочую карточку (ЗВ=ЗВ-2026-001)
scenarios.zv = async (browser) => {
  const r = new Report("zv");
  const ZV = process.env.ZV ?? "ЗВ-2026-001";
  const places = [
    ["director", "КП на одобрение (список)", "/eds/drafts"],
    ["director", "письмо ВХ", `/eds/inbox/${encodeURIComponent(process.env.LETTER ?? "ВХ-001/26")}`],
    ["director", "проект", PROJ],
    ["director", "Все проекты", "/eds/projects"],
    ["director", "Все документы", "/eds/documents"],
    ["manager_all", "клиент (карточка в CRM)", "/crm/clients"],
    ["manager_all", "Заявки в расчёте", "/erp/requests"],
  ];
  let last = "";
  let page;
  for (const [key, label, path] of places) {
    if (key !== last) {
      if (page) await page.context().close();
      ({ page } = await np(browser));
      await signIn(page, r, PEOPLE[key].email, pwOf(PEOPLE[key].email));
      last = key;
    }
    await spaGoto(page, path);
    await settle(page);
    const links = page.getByRole("link", { name: new RegExp(ZV) });
    const n = await links.count();
    const plain = await page.getByText(ZV).count();
    let target = "";
    if (n) target = (await links.first().getAttribute("href")) ?? "";
    console.log(`ZV ${key} | ${label} | ссылок: ${n} | упоминаний: ${plain} | ${target}`);
    r.note(`${label}`, `ссылок ${n}, упоминаний ${plain}, ${target}`);
    if (n) {
      const box = await links.first().boundingBox();
      const covered = await links.first().evaluate((el) => { const b = el.getBoundingClientRect(); const t = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2); return !(t === el || el.contains(t)); });
      console.log(`  ссылка x=${Math.round(box?.x ?? 0)} перекрыта панелью: ${covered}`);
    }
  }
  // поиск ⌘K
  await page.keyboard.press("Control+k");
  await page.waitForTimeout(500);
  await page.getByRole("combobox").or(page.getByRole("searchbox")).first().fill(ZV).catch(() => {});
  await page.waitForTimeout(2500);
  out("поиск", await txt(page, "body"), 600);
  r.save();
};
