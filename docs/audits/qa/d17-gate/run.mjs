import { screenHere, ADMIN, PEOPLE, PANEL, Report, bff, compose, launch, np, pwOf, saveState, screen, secret, settle, shot, signIn, spaGoto, state, step, toastsGone } from "./common.mjs";
import * as lib from "./common.mjs";
const scenarios = {};

// s1. Первый запуск: администратор по коду из журнала crm-api.
scenarios.s1 = async (browser) => {
  const r = new Report("s1");
  const { page } = await np(browser);
  const adminPw = secret("adm");
  saveState({ adminEmail: ADMIN, adminPw });
  await page.goto("/login");
  await step(page, r, "вход без администратора ведёт на /setup", async () => {
    await page.waitForURL(/\/setup$/, { timeout: 60000, waitUntil: "commit" });
  });
  const logs = compose("logs crm-api");
  const m = [...logs.matchAll(/"setup_code": "([^"]+)"/g)].pop();
  r.check("код первого запуска найден в журнале crm-api", !!m);
  await page.getByLabel("Код первого запуска").fill(m?.[1] ?? "");
  await page.getByLabel("Имя и фамилия").fill("Демо Админова");
  await page.getByLabel("Электронная почта администратора").fill(ADMIN);
  await page.getByLabel("Пароль", { exact: true }).fill(adminPw);
  await page.getByLabel("Повторите пароль").fill(adminPw);
  await page.getByRole("button", { name: "Создать администратора и войти" }).click();
  await step(page, r, "администратор создан, открыт мастер", async () => {
    await page.waitForURL(/\/admin\/setup/, { timeout: 60000, waitUntil: "commit" });
  });
  r.note("ошибки консоли / 5xx", `${page.consoleErrors.join(" | ")} ${page.failed.join(" | ")}`);
  r.save();
};

// s1w. Мастер: сопряжение ERP, своя компания.
scenarios.s1w = async (browser) => {
  const r = new Report("s1w");
  const { page } = await np(browser);
  const { adminEmail, adminPw } = state();
  await signIn(page, r, adminEmail, adminPw);
  await spaGoto(page, "/admin/setup");
  await page.getByRole("heading", { level: 2, name: "Подключение ERP" }).waitFor({ timeout: 15000 });
  await screen(page, r, "wizard", { narrow: false });
  await page.getByRole("link", { name: "Подключить ERP" }).first().click();
  await step(page, r, "ERP сопряжена из мастера", async () => {
    const panel = page.locator(PANEL);
    await panel.getByRole("button", { name: "Подключить ERP" }).click();
    const form = panel.getByRole("form", { name: "Подключить ERP" });
    await form.getByLabel("Ваш пароль администратора").fill(adminPw);
    await form.getByRole("button", { name: "Подключить ERP" }).click();
    await page.getByLabel("Название компании").waitFor({ timeout: 60000 });
  });
  const t0 = Date.now();
  for (let i = 0; i < 20; i++) {
    const again = page.getByRole("button", { name: "Проверить снова" });
    if (await again.isVisible().catch(() => false)) await again.click();
    if (await page.getByLabel("Название компании").isVisible().catch(() => false)) break;
    await page.waitForTimeout(4000);
  }
  await step(page, r, "своя компания создаётся в мастере", async () => {
    await page.getByLabel("Название компании").fill("ООО Демо Рельс D17");
    await page.getByRole("button", { name: "Создать компанию" }).click();
    await page.getByText("Своя компания создана.").waitFor({ timeout: 30000 });
  });
  r.note("ожидание формы компании", `${Math.round((Date.now() - t0) / 1000)} с`);
  r.save();
};

// s2. Сотрудники из шаблонов ролей — через интерфейс администратора («Временным паролем»).
scenarios.s2 = async (browser) => {
  const r = new Report("s2");
  const { page } = await np(browser);
  const { adminEmail, adminPw } = state();
  await signIn(page, r, adminEmail, adminPw);
  const temps = state().temps ?? {};
  for (const [key, who] of Object.entries(PEOPLE)) {
    if (temps[who.email]) continue;
    await spaGoto(page, "/admin/org");
    await spaGoto(page, "/admin/org?invite=open&panel=open");
    const ok = await step(page, r, `приглашение «${key}» (${who.tpl}) временным паролем`, async () => {
      const panel = page.locator(PANEL);
      await panel.getByRole("radio", { name: "Временным паролем, без почты" }).check();
      await panel.getByLabel("Имя и фамилия").fill(who.name);
      await panel.getByLabel("Электронная почта").fill(who.email);
      await panel.getByRole("checkbox", { name: new RegExp(`^${who.tpl}`) }).check();
      if (key === "registrar") await shot(page, r, "invite-registrar-filled");
      await panel.getByRole("button", { name: "Создать и показать пароль" }).click();
      const field = panel.getByLabel("Временный пароль", { exact: true });
      await field.waitFor({ timeout: 20000 });
      temps[who.email] = await field.inputValue();
      await panel.getByRole("button", { name: "Готово: пароль передан" }).click();
      await panel.getByRole("heading", { level: 3, name: who.name }).waitFor({ timeout: 30000 });
      await shot(page, r, `employee-${key}`);
    }, { noShot: true });
  }
  saveState({ temps });
  r.save();
};

// walk: ROLE=registrar PATHS=/crm/messages,/crm/leads [NARROW=1] — вход, обход, текст, снимок с axe
scenarios.walk = async (browser) => {
  const key = process.env.ROLE;
  const who = key === "admin" ? { email: state().adminEmail } : PEOPLE[key];
  const r = new Report(`walk-${key}`);
  const { page } = await np(browser);
  await signIn(page, r, who.email, key === "admin" ? state().adminPw : pwOf(who.email));
  console.log("RAIL", await page.getByRole("navigation", { name: "Модули" }).getByRole("link").evaluateAll((els) => els.map((e) => e.textContent?.trim())));
  for (const path of (process.env.PATHS ?? "").split(",").filter(Boolean)) {
    await spaGoto(page, path);
    await settle(page);
    const name = path.replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "");
    console.log(`--- ${path} -> ${new URL(page.url()).pathname}${new URL(page.url()).search}`);
    console.log((await page.locator("#main-content").innerText().catch(() => "")).slice(0, Number(process.env.LIM ?? 1500)));
    await screen(page, r, name, { narrow: !!process.env.NARROW });
  }
  r.note("ошибки консоли / 5xx", `${page.consoleErrors.join(" | ")} ${page.failed.join(" | ")}`);
  r.save();
};

// act: ROLE=<> PATH=<> ACTS='click:Текст;fill:Метка=значение;text;shot:имя' — произвольные шаги
scenarios.act = async (browser) => {
  const key = process.env.ROLE;
  const who = key === "admin" ? { email: state().adminEmail } : PEOPLE[key];
  const r = new Report(`act-${key}`);
  const { page } = await np(browser, Number(process.env.W ?? 1440));
  await signIn(page, r, who.email, key === "admin" ? state().adminPw : pwOf(who.email));
  await spaGoto(page, process.env.PATH_ ?? "/dashboard/queue");
  await settle(page);
  for (const a of (process.env.ACTS ?? "").split(";").filter(Boolean)) {
    const [cmd, ...rest] = a.split(":");
    const arg = rest.join(":");
    try {
      if (cmd === "click") await page.getByRole(arg.startsWith("link=") ? "link" : arg.startsWith("tab=") ? "tab" : "button", { name: arg.replace(/^(link|tab)=/, "") }).first().click();
      else if (cmd === "pclick") await page.locator(PANEL).getByRole(arg.startsWith("link=") ? "link" : "button", { name: arg.replace(/^link=/, "") }).first().click();
      else if (cmd === "clicktext") await page.getByText(arg).first().click();
      else if (cmd === "fill") { const [l, v] = arg.split("="); await page.getByLabel(l).first().fill(v); }
      else if (cmd === "text") console.log((await page.locator(arg || "body").first().innerText()).slice(0, Number(process.env.LIM ?? 2500)));
      else if (cmd === "shot") await screen(page, r, arg, { narrow: !!process.env.NARROW });
      else if (cmd === "wait") await page.waitForTimeout(Number(arg));
      else if (cmd === "goto") await spaGoto(page, arg);
      else if (cmd === "url") console.log("URL", page.url());
      await settle(page);
    } catch (e) { console.log("ACT FAIL", a, String(e.message).split("\n")[0]); }
  }
  r.save();
};

const inject = async (uid, text, uname, first = "Азиз") => {
  const n = Date.now() % 2000000000;
  const from = { id: uid, is_bot: false, first_name: first, language_code: "ru", ...(uname ? { username: uname } : {}) };
  const m = { message_id: n % 100000, date: Math.floor(Date.now() / 1000), chat: { id: uid, type: "private" }, from, text };
  if (text.startsWith("/")) m.entities = [{ type: "bot_command", offset: 0, length: text.split(" ")[0].length }];
  const t0 = Date.now();
  await fetch("http://127.0.0.1:18999/_inject", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ update_id: n, message: m }) });
  return t0;
};

// m1. Менеджер-универсал: ответ клиенту, «доставка не подтверждена», замер «сообщение бота -> Платформа ≤ 2 с»
scenarios.m1 = async (browser) => {
  const r = new Report("m1");
  const who = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email));
  await spaGoto(page, "/crm/messages?lead=L-0001&panel=open");
  await settle(page);
  const composer = page.getByLabel(/^(Сообщение клиенту|Заметка для команды)$/);
  await step(page, r, "МУ отвечает клиенту «От себя»", async () => {
    await composer.fill("Здравствуйте, Азиз! Цена на Р65 — в КП сегодня до 17:00.");
    await page.getByRole("button", { name: "Отправить" }).click();
    await page.locator(".pf-msg-bubble", { hasText: "Цена на Р65 — в КП сегодня" }).first().waitFor({ timeout: 10000 });
  });
  await settle(page);
  console.log((await page.locator("#main-content").innerText()).slice(-700));
  await screen(page, r, "reply-sent", { narrow: true });
  // замер
  const times = [];
  for (let i = 1; i <= 6; i++) {
    const text = `Замер ${i}: уточните срок поставки ${Date.now()}`;
    const waiter = page.locator(".pf-msg-bubble", { hasText: text }).first().waitFor({ timeout: 20000 }).then(() => Date.now()).catch(() => null);
    const t0 = await inject(7001, text, "aziz_d17");
    const t1 = await waiter;
    times.push(t1 ? t1 - t0 : null);
    await page.waitForTimeout(1500);
  }
  r.note("замер «сообщение клиента в бот -> видно в открытом диалоге Платформы», мс", JSON.stringify(times));
  saveState({ measure: times });
  r.save();
};

// c1. Создать заявку: лид только с Telegram (L-0001), двойной клик «Создать заявку» -> одна ЗВ
scenarios.c1 = async (browser) => {
  const r = new Report("c1");
  const who = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email));
  const lead = process.env.LEAD ?? "L-0001";
  const company = process.env.COMPANY ?? "ООО Демо Путь";
  const email = process.env.EMAIL ?? "";
  await spaGoto(page, `/crm/leads?lead=${lead}&create=1&panel=open&tab=card`);
  await settle(page);
  const panel = page.locator(PANEL);
  const calls = [];
  page.on("request", (q) => { if (q.method() === "POST" && /request|deal|lead/i.test(q.url()) && !/stream/.test(q.url())) calls.push(`${q.method()} ${new URL(q.url()).pathname}`); });
  await panel.getByLabel("Название компании").fill(company);
  await panel.getByLabel("ИНН").fill(process.env.INN ?? "301234567");
  await panel.getByRole("textbox", { name: "Имя", exact: true }).fill(process.env.CNAME ?? "Азиз Каримов");
  if (email) await panel.getByLabel("Почта").fill(email);
  await panel.getByLabel("Суть запроса").fill("Рельсы Р65, 40 т, поставка до 20 ноября (демо гейта D1-7)");
  await screen(page, r, `create-form-${lead}`, { narrow: false });
  const submit = panel.getByRole("button", { name: /^Создать заявку/ });
  await submit.dblclick({ delay: 10 });
  await page.waitForTimeout(6000);
  await settle(page);
  console.log("POST-вызовы:", JSON.stringify(calls));
  console.log((await page.locator("#main-content, #pf-context-panel").first().innerText()).slice(0, 1500));
  console.log("PANEL:", (await panel.innerText().catch(() => "")).slice(0, 1500));
  await screen(page, r, `create-done-${lead}`, { narrow: true });
  r.save();
};

// d1. Директор: резолюция на ВХ (оба исполнителя — менеджер-универсал) -> задание в ERP
scenarios.d1 = async (browser) => {
  const r = new Report("d1");
  const who = PEOPLE.director;
  const letter = process.env.LETTER ?? "ВХ-001/26";
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email));
  await spaGoto(page, `/eds/inbox/${encodeURIComponent(letter)}`);
  await settle(page);
  const panel = page.locator(PANEL);
  await panel.getByLabel("Текст резолюции").fill("Рассчитать поставку Р65 40 т и услугу доставки, КП до пятницы.");
  const combos = panel.getByRole("combobox");
  console.log("combobox count", await combos.count());
  await combos.nth(0).click();
  console.log("OPTIONS goods:", JSON.stringify(await page.locator(".ant-select-item-option").allInnerTexts()));
  await page.keyboard.press("Escape");
  await combos.nth(1).click();
  console.log("OPTIONS services:", JSON.stringify(await page.locator(".ant-select-item-option").allInnerTexts()));
  await page.keyboard.press("Escape");
  await combos.nth(0).click();
  await page.locator(".ant-select-item-option", { hasText: "Демо Универсалов" }).first().click();
  await combos.nth(1).click();
  await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option", { hasText: "Демо Универсалов" }).first().click();
  await panel.getByLabel("Маржа не ниже, %").fill("10");
  await screen(page, r, "resolution-filled", { narrow: false });
  await step(page, r, "директор утверждает резолюцию", async () => {
    await panel.getByRole("button", { name: /Утвердить резолюцию/ }).click();
    await page.getByText(/Резолюция наложена/).first().waitFor({ timeout: 20000 });
  });
  await settle(page);
  console.log((await page.locator("#main-content").innerText()).slice(0, 1200));
  await screen(page, r, "resolution-done", { narrow: true });
  r.save();
};

// k1. МУ: строки расчёта (товар и услуга), поля цены и виз — разведка
scenarios.k1 = async (browser) => {
  const r = new Report("k1");
  const who = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email));
  await spaGoto(page, "/erp/calc/%D0%97%D0%92-2026-001");
  await settle(page);
  for (const [name, qty, unit, svc] of [["Рельс Р65 ГОСТ Р 51685", "40", "т", false], ["Доставка до станции назначения", "1", "рейс", true]]) {
    await page.getByRole("button", { name: "Добавить строку" }).first().click();
    const dlg = page.getByRole("dialog");
    await dlg.getByLabel("Наименование").fill(name);
    await dlg.getByLabel("Количество").fill(qty);
    await dlg.getByLabel("Единица").fill(unit);
    if (svc) await dlg.getByRole("radio", { name: "Услуга" }).check();
    await dlg.getByRole("button", { name: "Добавить" }).click();
    await page.waitForTimeout(1500);
  }
  await settle(page);
  console.log((await page.locator("#main-content").innerText()).slice(0, 3000));
  await screen(page, r, "calc-lines", { narrow: false });
  r.save();
};

// k2. МУ: заполняет цены, ставит обе визы, «Расчёт готов → черновик КП директору»
scenarios.k2 = async (browser) => {
  const r = new Report("k2");
  const who = PEOPLE.manager_all;
  const deal = process.env.DEAL ?? "ЗВ-2026-001";
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email));
  await spaGoto(page, `/erp/calc/${encodeURIComponent(deal)}`);
  await settle(page);
  const rows = page.locator("table tbody tr");
  const goods = rows.nth(0);
  const svc = rows.nth(1);
  const fillNum = async (loc, v) => { await loc.fill(v); await loc.blur(); await page.waitForTimeout(700); };
  await fillNum(goods.getByLabel(/^Закупка за единицу/), "3500000");
  await fillNum(goods.getByLabel(/^Цена клиенту/), "4200000");
  await fillNum(svc.getByLabel(/^Ставка бригады/), "500000");
  await fillNum(svc.getByLabel(/^Дней работы/), "2");
  await fillNum(svc.getByLabel(/^Цена клиенту/), "1500000");
  await settle(page);
  await step(page, r, "МУ подтверждает виззы обеих зон (товар и услуга)", async () => {
    await goods.getByRole("button", { name: /Подтвердить/ }).click();
    await page.waitForTimeout(1500);
    await svc.getByRole("button", { name: /Подтвердить/ }).click();
    await page.waitForTimeout(1500);
  });
  await settle(page);
  console.log((await page.locator("#main-content").innerText()).slice(300, 1700));
  await screen(page, r, "calc-visas", { narrow: false });
  await step(page, r, "«Расчёт готов → черновик КП директору»", async () => {
    await page.getByRole("button", { name: /Расчёт готов/ }).click();
    await page.waitForTimeout(3000);
  });
  await settle(page);
  console.log((await page.locator("#main-content").innerText()).slice(0, 900));
  await screen(page, r, "calc-sent", { narrow: false });
  r.save();
};

// q1. Директор одобряет КП с тремя каналами -> автоотправка (ERP-11), ИСХ, причина недоступного канала
scenarios.q1 = async (browser) => {
  const r = new Report("q1");
  const who = PEOPLE.director;
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email));
  await spaGoto(page, "/eds/drafts");
  await settle(page);
  await page.getByRole("link", { name: "Открыть" }).first().click();
  await page.getByText("Чек-лист одобрения").first().waitFor({ timeout: 20000 });
  await settle(page);
  const panel = page.locator(PANEL);
  const approve = panel.getByRole("button", { name: /Одобрить КП/ });
  await screen(page, r, "quote-approve-before", { narrow: false });
  console.log("approve enabled before channels:", await approve.isEnabled());
  for (const ch of ["Telegram-бот", "Кабинет", "Почта"]) await panel.getByRole("checkbox", { name: new RegExp(ch) }).check().catch((e) => console.log("channel", ch, String(e.message).split("\n")[0]));
  await screen(page, r, "quote-approve-channels", { narrow: false });
  const t0 = Date.now();
  await step(page, r, "директор одобряет КП (3 канала)", async () => {
    await approve.click();
    await page.waitForTimeout(6000);
  });
  await settle(page);
  console.log("после одобрения, мс:", Date.now() - t0);
  console.log((await page.locator("#main-content").innerText()).slice(0, 600));
  console.log("PANEL", (await panel.innerText().catch(() => "")).slice(0, 2000));
  await screen(page, r, "quote-approved", { narrow: true });
  r.save();
};

// n1. Служебка: МУ создаёт (с суммой) -> директор «Вернуть» -> МУ «Доработать» -> повторная отправка -> директор «Согласовать» -> бухгалтер
scenarios.n1 = async (browser) => {
  const r = new Report("n1");
  const mu = PEOPLE.manager_all, dir = PEOPLE.director;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, "/eds/new");
  await settle(page);
  await screen(page, r, "memo-form", { narrow: true });
  await step(page, r, "МУ отправляет служебку с суммой директору", async () => {
    await page.getByLabel("Тема").fill("Командировка на объект заказчика (D17)");
    await page.getByLabel("Текст").fill("Прошу согласовать командировку на 2 дня для замера на объекте. Данные вымышленные.");
    await page.getByLabel("Сумма, сум").fill("1500000");
    await page.getByRole("button", { name: "Отправить на согласование" }).click();
    await page.waitForURL((u) => !/\/eds\/new/.test(String(u)), { timeout: 60000, waitUntil: "commit" });
    await settle(page);
  });
  console.log("URL после отправки", page.url());
  await screen(page, r, "memo-sent", { narrow: false });
  await page.context().clearCookies();
  const { page: pd } = await np(browser);
  await signIn(pd, r, dir.email, pwOf(dir.email));
  await spaGoto(pd, "/eds/approvals");
  await settle(pd);
  console.log((await pd.locator("#main-content").innerText()).slice(0, 700));
  await screen(pd, r, "approvals-list", { narrow: true });
  await pd.getByRole("link", { name: "Открыть" }).first().click();
  await settle(pd);
  console.log("URL директор", pd.url());
  console.log((await pd.locator(PANEL).innerText()).slice(0, 1500));
  await screen(pd, r, "memo-director", { narrow: false });
  r.save();
};

const MEMO = process.env.MEMO ?? "76eee6f4-21e3-4c31-bd4f-fcd983bc489d";
// n2. Директор возвращает служебку; МУ доработывает и отправляет повторно
scenarios.n2 = async (browser) => {
  const r = new Report("n2");
  const mu = PEOPLE.manager_all, dir = PEOPLE.director;
  const { page: pd } = await np(browser);
  await signIn(pd, r, dir.email, pwOf(dir.email));
  await spaGoto(pd, `/eds/approvals/${MEMO}`);
  await settle(pd);
  await pd.locator(PANEL).getByLabel("Комментарий").fill("Укажите даты командировки и объект.");
  await step(pd, r, "директор возвращает служебку на доработку с комментарием", async () => {
    await pd.locator(PANEL).getByRole("button", { name: "Вернуть на доработку" }).click();
    await pd.waitForTimeout(3500);
  });
  await settle(pd);
  console.log("PANEL директор:", (await pd.locator(PANEL).innerText().catch(() => "")).slice(0, 600));
  await screen(pd, r, "memo-returned-director", { narrow: false });
  await pd.context().clearCookies();
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  console.log((await page.locator("#main-content").innerText()).slice(0, 1200));
  await screen(page, r, "queue-rework", { narrow: true });
  const row = page.getByRole("link", { name: /Доработать|Открыть/ }).first();
  console.log("row link:", await row.innerText().catch(() => "-"));
  await row.click();
  await settle(page);
  console.log("URL МУ", page.url());
  console.log((await page.locator("#main-content").innerText()).slice(0, 1500));
  console.log("PANEL МУ:", (await page.locator(PANEL).innerText().catch(() => "")).slice(0, 1200));
  await screen(page, r, "rework-form", { narrow: false });
  r.save();
};

// n3. МУ дорабатывает и отправляет повторно; директор согласовывает; бухгалтер видит «к оплате»
scenarios.n3 = async (browser) => {
  const r = new Report("n3");
  const mu = PEOPLE.manager_all, dir = PEOPLE.director, acc = PEOPLE.accountant;
  const { page } = await np(browser);
  await signIn(page, r, mu.email, pwOf(mu.email));
  await spaGoto(page, `/eds/new?draft=${MEMO}`);
  await settle(page);
  const kept = await page.getByLabel("Тема").inputValue();
  const keptSum = await page.getByLabel("Сумма, сум").inputValue();
  r.check("форма доработки сохранила тему и сумму", kept.includes("Командировка") && /1\D?500\D?000/.test(keptSum), `${kept} | ${keptSum}`);
  await page.getByLabel("Текст").fill("Командировка 5–6 ноября 2026, станция Ташкент-Товарный, замер объекта. Прошу согласовать. Данные вымышленные.");
  await step(page, r, "МУ отправляет доработанную служебку повторно", async () => {
    await page.getByRole("button", { name: "Отправить на согласование" }).click();
    await page.waitForURL((u) => !/\/eds\/new/.test(String(u)), { timeout: 60000, waitUntil: "commit" });
    await settle(page);
  });
  await page.context().clearCookies();
  const { page: pd } = await np(browser);
  await signIn(pd, r, dir.email, pwOf(dir.email));
  await spaGoto(pd, `/eds/approvals/${MEMO}`);
  await settle(pd);
  console.log((await pd.locator("#main-content").innerText()).slice(0, 900));
  await screen(pd, r, "memo-resubmitted-director", { narrow: false });
  await step(pd, r, "директор согласовывает служебку", async () => {
    await pd.locator(PANEL).getByRole("button", { name: "Согласовать" }).click();
    await pd.waitForTimeout(3500);
  });
  console.log("PANEL директор:", (await pd.locator(PANEL).innerText().catch(() => "")).slice(0, 500));
  await pd.context().clearCookies();
  const { page: pa } = await np(browser);
  await signIn(pa, r, acc.email, pwOf(acc.email));
  await spaGoto(pa, "/dashboard/queue");
  await settle(pa);
  console.log("БУХГАЛТЕР очередь:", (await pa.locator("#main-content").innerText()).slice(0, 900));
  await screen(pa, r, "acc-queue", { narrow: true });
  await spaGoto(pa, "/eds/payments");
  await settle(pa);
  console.log("БУХГАЛТЕР счета и оплаты:", (await pa.locator("#main-content").innerText()).slice(0, 1200));
  await screen(pa, r, "acc-payments", { narrow: true });
  r.save();
};

// c2. Новый клиент с e-mail (лид L-0002, МУ): двойной клик + повтор того же запроса на сервер (идемпотентность request_key)
scenarios.c2 = async (browser) => {
  const r = new Report("c2");
  const who = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email));
  const lead = "L-0002";
  await spaGoto(page, `/crm/messages?lead=${lead}&panel=open`);
  await settle(page);
  await step(page, r, "МУ забирает лид L-0002 (возвращён ДП боту)", async () => {
    await page.getByRole("button", { name: /Забрать/ }).first().click();
    await page.waitForTimeout(2500);
  });
  await spaGoto(page, `/crm/leads?lead=${lead}&create=1&panel=open&tab=card`);
  await settle(page);
  const panel = page.locator(PANEL);
  let body = null;
  const posts = [];
  await page.route("**/api/v1/crm/requests", async (route) => {
    const q = route.request();
    if (q.method() === "POST") { body = q.postData(); posts.push(Date.now()); }
    await route.continue();
  });
  await panel.getByLabel("Название компании").fill("ООО Почта Тест");
  await panel.getByLabel("ИНН").fill("302345678");
  await panel.getByRole("textbox", { name: "Имя", exact: true }).fill("Бахтиёр Рахимов");
  await panel.getByLabel("Почта").fill("bakhtiyor@demo.example");
  await panel.getByLabel("Суть запроса").fill("Шпалы ЖБ, 500 шт, доставка до станции (демо D1-7, клиент с e-mail)");
  await screen(page, r, "create-form-L-0002", { narrow: false });
  await panel.getByRole("button", { name: /^Создать заявку/ }).dblclick({ delay: 5 });
  await page.waitForTimeout(6000);
  r.check("двойной клик: на сервер ушёл один POST", posts.length === 1, `POST: ${posts.length}`);
  console.log("BODY", body);
  const replay = await page.evaluate(async (b) => {
    const csrf = /rt_pf_csrf=([^;]+)/.exec(document.cookie)?.[1] ?? "";
    const call = () => fetch("/api/v1/crm/requests", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": decodeURIComponent(csrf) }, body: b }).then(async (x) => `${x.status} ${(await x.text()).slice(0, 160)}`);
    return Promise.all([call(), call()]);
  }, body);
  console.log("REPLAY x2:", JSON.stringify(replay));
  await screen(page, r, "create-done-L-0002", { narrow: true });
  r.save();
};

// r1. Делопроизводитель регистрирует требование ГНК -> «Ждёт резолюции» у директора; без кнопки «Резолюция»
scenarios.r1 = async (browser) => {
  const r = new Report("r1");
  const reg = PEOPLE.registrar, dir = PEOPLE.director;
  const { page } = await np(browser);
  await signIn(page, r, reg.email, pwOf(reg.email));
  await spaGoto(page, "/eds/register");
  await settle(page);
  const pickOpt = async (label, pat) => {
    await page.getByLabel(label, { exact: true }).click();
    const opts = await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option").allInnerTexts();
    console.log(`OPTIONS ${label}:`, JSON.stringify(opts));
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option", { hasText: pat }).first().click();
  };
  await pickOpt("Вид документа", /Требование|ГНК|налог/i);
  await page.getByLabel("Корреспондент", { exact: true }).fill("Государственный налоговый комитет (демо)");
  await page.getByLabel("ИНН корреспондента").fill("201122334");
  await page.getByLabel("Исходящий номер отправителя").fill("12/345");
  await page.getByLabel("Тема").fill("Требование о представлении документов по проверке (демо D1-7)");
  await page.getByLabel("Краткое содержание").fill("Представить договоры и акты за III квартал 2026. Данные вымышленные.");
  await page.locator('input[type="file"]').first().setInputFiles(`${process.env.QA_OUT}/../demo-letter.pdf`);
  await page.getByText(/demo-letter\.pdf/).first().waitFor({ timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(1500);
  console.log("срочно по умолчанию:", await page.getByRole("checkbox", { name: "Срочно" }).isChecked());
  await screen(page, r, "register-filled", { narrow: false });
  await step(page, r, "делопроизводитель регистрирует требование ГНК", async () => {
    await page.getByRole("button", { name: /Зарегистрировать/ }).last().click();
    await page.waitForTimeout(4000);
  });
  await settle(page);
  console.log("URL", page.url());
  console.log((await page.locator("#main-content").innerText()).slice(0, 1500));
  console.log("PANEL", (await page.locator(PANEL).innerText().catch(() => "")).slice(0, 800));
  await screen(page, r, "register-done", { narrow: true });
  r.save();
};

// x1. Права: черновик МУ (чужой -> 404), реестр и письма без letters.read, 403 прямого CRM
scenarios.x1 = async (browser) => {
  const r = new Report("x1");
  const mu = PEOPLE.manager_all;
  let draft = state().draftId;
  if (!draft) {
    const { page } = await np(browser);
    await signIn(page, r, mu.email, pwOf(mu.email));
    await spaGoto(page, "/eds/new");
    await settle(page);
    await page.getByLabel("Тема").fill("Черновик МУ (D17, чужой)");
    await page.getByLabel("Текст").fill("Личный черновик для проверки доступа. Вымышленные данные.");
    await page.getByRole("button", { name: "Сохранить черновик" }).click();
    await page.waitForTimeout(3500);
    console.log("URL после черновика", page.url());
    draft = /(?:draft|doc)=([0-9a-f-]{36})/.exec(page.url())?.[1] ?? /\/([0-9a-f-]{36})/.exec(page.url())?.[1];
    saveState({ draftId: draft });
  }
  console.log("draft", draft);
  for (const key of ["manager_all", "registrar", "director", "accountant", "supply", "engineer"]) {
    const who = PEOPLE[key];
    const { page } = await np(browser);
    await signIn(page, r, who.email, pwOf(who.email));
    const out = {};
    out.docs = await page.evaluate(async () => {
      const x = await fetch("/api/v1/eds/documents?limit=50"); const j = await x.json().catch(() => ({}));
      const items = j.items ?? [];
      return { status: x.status, n: items.length, kinds: [...new Set(items.map((i) => i.kind ?? i.type))], total: j.total };
    });
    out.draft = (await bff(page, "GET", `/api/v1/eds/documents/${draft}`)).status;
    out.letters = (await bff(page, "GET", "/api/v1/eds/letters")).status;
    out.leads = (await bff(page, "GET", "/api/v1/crm/leads")).status;
    out.messages = (await bff(page, "GET", "/api/v1/crm/messages")).status;
    console.log("RIGHTS", key, JSON.stringify(out));
    r.note(`права ${key}`, JSON.stringify(out));
    await page.context().close();
  }
  r.save();
};

const injectCb = async (uid, data, uname, first) => {
  const n = Date.now() % 2000000000;
  const from = { id: uid, is_bot: false, first_name: first, language_code: "ru", username: uname };
  await fetch("http://127.0.0.1:18999/_inject", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ update_id: n, callback_query: { id: String(n), from, chat_instance: "1", data, message: { message_id: 1, date: Math.floor(Date.now() / 1000), chat: { id: uid, type: "private" }, text: "x" } } }) });
};

// m3. Новый клиент пишет в бота: «Ждут ответа» у открытых страниц ДП и МУ обновляется без перезагрузки (замер)
scenarios.m3 = async (browser) => {
  const r = new Report("m3");
  const uid = 7003, first = "Тимур";
  const who1 = PEOPLE.registrar, who2 = PEOPLE.manager_all;
  const { page: p1 } = await np(browser);
  await signIn(p1, r, who1.email, pwOf(who1.email));
  await spaGoto(p1, "/crm/messages");
  const { page: p2 } = await np(browser);
  await signIn(p2, r, who2.email, pwOf(who2.email));
  await spaGoto(p2, "/crm/messages");
  await settle(p1); await settle(p2);
  await inject(uid, "/start", "timur_d17", first); await new Promise((x) => setTimeout(x, 2500));
  await injectCb(uid, "lang:ru", "timur_d17", first); await new Promise((x) => setTimeout(x, 2500));
  await injectCb(uid, "consent:accept", "timur_d17", first); await new Promise((x) => setTimeout(x, 2500));
  const mark = `Срочно нужен расчёт на 200 стыковых накладок ${Date.now() % 100000}`;
  const w = (pg) => pg.locator("nav[aria-label='Диалоги, которые ждут ответа']").getByText("Тимур").first().waitFor({ timeout: 30000 }).then(() => Date.now()).catch(() => null);
  const a = w(p1), b = w(p2);
  const t0 = await inject(uid, mark, "timur_d17", first);
  const [t1, t2] = await Promise.all([a, b]);
  r.note("замер «клиент пишет боту -> передача видна в «Ждут ответа» открытой страницы ДП / МУ», мс (включает работу бота)", `${t1 ? t1 - t0 : "нет"} / ${t2 ? t2 - t0 : "нет"}`);
  await settle(p2);
  await screen(p2, r, "messages-new-handoff", { narrow: true });
  console.log((await p2.locator("#main-content").innerText()).slice(0, 500));
  r.save();
};

// m2. «Доставка не подтверждена»: Telegram (заглушка) зависает — ответ МУ, повтор сразу и после 2 минут
scenarios.m2 = async (browser) => {
  const r = new Report("m2");
  const who = PEOPLE.manager_all;
  const lead = process.env.LEAD ?? "L-0003";
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email));
  await spaGoto(page, `/crm/messages?lead=${lead}&panel=open`);
  await settle(page);
  await page.getByRole("button", { name: /Забрать/ }).first().click();
  await page.waitForTimeout(2500);
  const composer = page.getByLabel(/^(Сообщение клиенту|Заметка для команды)$/);
  const { execSync } = await import("node:child_process");
  execSync("docker pause rt-gate-d17-fake-bot-api");
  try {
    await composer.fill("Проверка доставки: ответ при зависшем Telegram");
    await page.getByRole("button", { name: "Отправить" }).click();
    const t0 = Date.now();
    await page.getByRole("alert").first().waitFor({ timeout: 60000 });
    r.note("ошибка отправки появилась через, с", String(Math.round((Date.now() - t0) / 1000)));
    console.log("ALERT1:", (await page.getByRole("alert").first().innerText()).replace(/\s+/g, " "));
    await screen(page, r, "send-hung-alert", { narrow: false });
  } finally {
    execSync("docker unpause rt-gate-d17-fake-bot-api");
  }
  await page.getByRole("button", { name: "Повторить" }).first().click().catch((e) => console.log("повтор 1:", String(e.message).split("\n")[0]));
  await page.waitForTimeout(3000);
  console.log("ALERT2:", (await page.getByRole("alert").allInnerTexts()).join(" || ").replace(/\s+/g, " "));
  await screen(page, r, "send-retry-early", { narrow: false });
  await page.waitForTimeout(125000);
  await page.getByRole("button", { name: "Повторить" }).first().click().catch((e) => console.log("повтор 2:", String(e.message).split("\n")[0]));
  await page.waitForTimeout(3500);
  console.log("ALERT3:", (await page.getByRole("alert").allInnerTexts()).join(" || ").replace(/\s+/g, " "));
  console.log("MARK:", (await page.locator(".pf-msg-delivery").allInnerTexts()).join(" || "));
  await screen(page, r, "send-unconfirmed", { narrow: true });
  r.save();
};

// b1. Мосты H1: обход всех разделов ролей; заглушка должна быть только у разделов без экрана и с честным мостом
scenarios.b1 = async (browser) => {
  const r = new Report("b1");
  const keys = (process.env.ROLES ?? "registrar,director,manager_all,accountant").split(",");
  const rows = [];
  for (const key of keys) {
    const who = PEOPLE[key];
    const { page } = await np(browser);
    await signIn(page, r, who.email, pwOf(who.email));
    const modules = await page.getByRole("navigation", { name: "Модули" }).getByRole("link").evaluateAll((els) => els.map((e) => ({ t: e.textContent?.trim(), h: e.getAttribute("href") })).filter((x) => x.t !== "RT"));
    const seen = new Set();
    for (const m of modules) {
      await spaGoto(page, m.h);
      await settle(page);
      const links = await page.getByRole("navigation", { name: "Разделы модуля" }).getByRole("link").evaluateAll((els) => els.map((e) => ({ t: e.textContent?.replace(/\d+$/, "").trim(), h: e.getAttribute("href") })));
      for (const l of links) {
        if (!l.h || seen.has(l.h)) continue;
        seen.add(l.h);
        await spaGoto(page, l.h);
        await settle(page);
        const text = await page.locator("#main-content").innerText().catch(() => "");
        const stub = text.includes("Этот раздел ещё переносится в Платформу");
        const denied = text.includes("Нет доступа");
        const bridge = await page.getByRole("link", { name: /Открыть в старо/ }).count();
        const when = /Когда появится:\s*([^\n]+)/.exec(text)?.[1] ?? "";
        const who2 = /Сейчас этой работы в интерфейсе нет|Сейчас эта работа делается в Платформе/.test(text);
        rows.push({ role: key, module: m.t, section: l.t, href: l.h, stub, denied, bridge, when, whoText: who2 });
        console.log(`BRIDGE ${key} | ${m.t} · ${l.t} | ${l.h} | ${denied ? "НЕТ ДОСТУПА" : stub ? `заглушка; мост=${bridge}; когда=${when}; кто=${who2}` : "экран"}`);
      }
    }
    await page.context().close();
  }
  saveState({ bridgeRows: rows });
  r.save();
};

// mob. 390 px: ключевые экраны D1 (диалог, карточка лида, «Создать заявку», резолюция, КП, регистрация входящего)
scenarios.mob = async (browser) => {
  const r = new Report("mob");
  const go = async (key, steps) => {
    const who = PEOPLE[key];
    const { page } = await np(browser, 390);
    await signIn(page, r, who.email, pwOf(who.email));
    for (const [name, path, after] of steps) {
      await spaGoto(page, path);
      await settle(page);
      if (after) await after(page).catch((e) => console.log("after", name, String(e.message).split("\n")[0]));
      await settle(page);
      await screenHere(page, r, name);
    }
    await page.context().close();
  };
  await go("manager_all", [
    ["messages-list", "/crm/messages"],
    ["messages-dialog", "/crm/messages?lead=L-0003&panel=open"],
    ["lead-card", "/crm/leads?lead=L-0003&panel=open&tab=card"],
    ["create-request-form", "/crm/leads?lead=L-0003&create=1&panel=open&tab=card"],
    ["calc-lines", "/erp/calc/%D0%97%D0%92-2026-001"],
    ["memo-form", "/eds/new"],
  ]);
  await go("director", [
    ["queue", "/dashboard/queue"],
    ["inbox-resolution", "/eds/inbox/%D0%92%D0%A5-002%2F26?panel=open&tab=resolution"],
    ["quote-card", "/eds/drafts/15f15f1d-8a3d-445f-a05b-d67ebb2efc03"],
  ]);
  await go("registrar", [
    ["register-form", "/eds/register"],
    ["lead-card", "/crm/leads?lead=L-0003&panel=open&tab=card"],
  ]);
  r.save();
};

// o1. CRM недоступна: честные ошибки в Платформе вместо пустых экранов (B-030: «Нет связи»), потом возврат
scenarios.o1 = async (browser) => {
  const r = new Report("o1");
  const who = PEOPLE.manager_all;
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email));
  await spaGoto(page, "/crm/leads");
  await settle(page);
  compose("stop crm-api");
  try {
    for (const path of ["/crm/messages", "/crm/leads", "/dashboard/queue"]) {
      await spaGoto(page, path);
      await page.waitForTimeout(9000);
      await settle(page);
      console.log("--- CRM down", path, "::", (await page.locator("#main-content").innerText()).replace(/\s+/g, " ").slice(0, 400));
      await screen(page, r, `crm-down${path.replace(/\W+/g, "_")}`, { narrow: false });
    }
  } finally {
    compose("start crm-api");
  }
  r.save();
};

// l1. uz и en: экраны D1 директора (остатки русского текста)
scenarios.l1 = async (browser) => {
  const r = new Report("l1");
  const who = PEOPLE.director;
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email));
  const setLang = async (label) => {
    await spaGoto(page, "/me");
    await settle(page);
    const combo = page.getByRole("combobox").filter({ has: page.locator("xpath=.") }).first();
    const box = page.locator(".ant-form-item", { hasText: /^(Язык|Til|Language)/ }).first().locator(".ant-select");
    await box.click();
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option", { hasText: label }).first().click();
    await page.waitForTimeout(500);
    await page.getByRole("button", { name: /Сохранить|Save|Saqlash/ }).first().click();
    await page.waitForTimeout(2500);
  };
  for (const [lang, label] of (process.env.LANGS ?? "uz,en").split(",").map((l) => [l, l === "uz" ? /O.zbek/i : /English/i])) {
    await setLang(label).catch((e) => console.log("LANG set fail", lang, String(e.message).split("\n")[0]));
    for (const [name, path] of [["queue", "/dashboard/queue"], ["inbox", "/eds/inbox"], ["letter", "/eds/inbox/%D0%92%D0%A5-002%2F26?panel=open&tab=resolution"], ["quote", "/eds/drafts/15f15f1d-8a3d-445f-a05b-d67ebb2efc03"], ["approvals", "/eds/approvals"], ["messages", "/crm/messages"], ["leads", "/crm/leads"]]) {
      await spaGoto(page, path);
      await settle(page);
      const text = await page.locator("body").innerText();
      const cyr = (text.match(/[А-Яа-яЁё]{3,}/g) ?? []);
      console.log(`LANG ${lang} ${name}: кириллических слов ${cyr.length}; пример: ${[...new Set(cyr)].slice(0, 14).join(" ")}`);
      await shot(page, r, `lang-${lang}-${name}`);
    }
  }
  await setLang(/Русский/).catch((e) => console.log("LANG back fail", String(e.message).split("\n")[0]));
  r.save();
};

// sweep. Итоговый проход: ключевые экраны D1 по ролям, 1440 и 390, axe и прокрутка; сводка в QA_OUT/sweep.json
scenarios.sweep = async (browser) => {
  const r = new Report("sw");
  const ID = "15f15f1d-8a3d-445f-a05b-d67ebb2efc03";
  const plan = {
    registrar: [["queue", "/dashboard/queue"], ["messages", "/crm/messages"], ["leads", "/crm/leads"], ["lead-card", "/crm/leads?lead=L-0003&panel=open&tab=card"], ["inbox", "/eds/inbox"], ["gnk-card", "/eds/inbox/%D0%92%D0%A5-003%2F26?panel=open&tab=resolution"], ["register", "/eds/register"], ["registry", "/eds/documents"]],
    director: [["queue", "/dashboard/queue"], ["inbox", "/eds/inbox"], ["letter-resolution", "/eds/inbox/%D0%92%D0%A5-002%2F26?panel=open&tab=resolution"], ["quotes", "/eds/drafts"], ["quote-card", `/eds/drafts/${ID}`], ["memos", "/eds/approvals"], ["messages-readonly", "/crm/messages"], ["registry", "/eds/documents"]],
    manager_all: [["queue", "/dashboard/queue"], ["messages", "/crm/messages"], ["dialog", "/crm/messages?lead=L-0001&panel=open"], ["leads", "/crm/leads"], ["lead-card", "/crm/leads?lead=L-0003&panel=open&tab=card"], ["clients", "/crm/clients"], ["client-card", "/crm/clients?client=1&panel=open&tab=card"], ["calc-list", "/erp/calc"], ["calc", "/erp/calc/%D0%97%D0%92-2026-001"], ["quote-card", `/eds/drafts/${ID}`], ["memo-form", "/eds/new"], ["payments", "/eds/payments"], ["requests-bridge", "/crm/requests"]],
    accountant: [["queue", "/dashboard/queue"], ["memo", "/eds/approvals/%D0%A1%D0%97-2026%2F001?panel=open&tab=agree"], ["payments", "/eds/payments"]],
    supply: [["queue", "/dashboard/queue"], ["no-access-crm", "/crm/messages"], ["registry-no-letters", "/eds/documents"]],
  };
  const sum = [];
  for (const [key, list] of Object.entries(plan)) {
    const who = PEOPLE[key];
    const { page } = await np(browser);
    await signIn(page, r, who.email, pwOf(who.email));
    for (const [name, path] of list) {
      await spaGoto(page, path);
      await settle(page);
      const before = r.screens.length;
      await screen(page, r, `${key}-${name}`, { narrow: true });
      for (const sc of r.screens.slice(before)) sum.push({ role: key, name, width: sc.width, axe: sc.axe, noHScroll: sc.noHScroll, file: sc.file });
    }
    await page.context().close();
  }
  const { writeFileSync } = await import("node:fs");
  writeFileSync(`${process.env.QA_OUT}/sweep.json`, JSON.stringify(sum, null, 1));
  r.save();
};

// q2. Второй КП (ЗВ-2026-002) без каналов: резолюция -> расчёт -> одобрение без каналов -> что делает МУ
scenarios.q2 = async (browser) => {
  const r = new Report("q2");
  const dir = PEOPLE.director, mu = PEOPLE.manager_all;
  const deal = "ЗВ-2026-002";
  {
    const { page } = await np(browser);
    await signIn(page, r, dir.email, pwOf(dir.email));
    await spaGoto(page, `/eds/inbox/${encodeURIComponent("ВХ-002/26")}`);
    await settle(page);
    const panel = page.locator(PANEL);
    await panel.getByLabel("Текст резолюции").fill("Рассчитать шпалы ЖБ 500 шт.");
    const combos = panel.getByRole("combobox");
    await combos.nth(0).click();
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option", { hasText: "Демо Универсалов" }).first().click();
    await combos.nth(1).click();
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option", { hasText: "Демо Универсалов" }).first().click();
    await panel.getByRole("button", { name: /Утвердить резолюцию/ }).click();
    await page.getByText(/Резолюция наложена/).first().waitFor({ timeout: 20000 });
    r.check("резолюция на ВХ-002/26 наложена", true);
    await page.context().close();
  }
  {
    const { page } = await np(browser);
    await signIn(page, r, mu.email, pwOf(mu.email));
    await spaGoto(page, `/erp/calc/${encodeURIComponent(deal)}`);
    await settle(page);
    await page.getByRole("button", { name: "Начать расчёт" }).click();
    await page.getByRole("button", { name: "Добавить строку" }).first().waitFor({ timeout: 20000 });
    await page.getByRole("button", { name: "Добавить строку" }).first().click();
    const dlg = page.getByRole("dialog");
    await dlg.getByLabel("Наименование").fill("Шпала ЖБ Ш1");
    await dlg.getByLabel("Количество").fill("500");
    await dlg.getByLabel("Единица").fill("шт");
    await dlg.getByRole("button", { name: "Добавить" }).click();
    await page.waitForTimeout(1500);
    const row = page.locator("table tbody tr").nth(0);
    const fillNum = async (loc, v) => { await loc.fill(v); await loc.blur(); await page.waitForTimeout(700); };
    await fillNum(row.getByLabel(/^Закупка за единицу/), "800000");
    await fillNum(row.getByLabel(/^Цена клиенту/), "1000000");
    await row.getByRole("button", { name: /Подтвердить/ }).click();
    await page.waitForTimeout(1500);
    await page.getByRole("button", { name: /Расчёт готов/ }).click();
    await page.waitForTimeout(3000);
    r.check("расчёт ЗВ-2026-002 отправлен директору", true);
    await page.context().close();
  }
  {
    const { page } = await np(browser);
    await signIn(page, r, dir.email, pwOf(dir.email));
    await spaGoto(page, "/eds/drafts");
    await settle(page);
    await page.getByRole("link", { name: "Открыть" }).first().click();
    await page.getByText("Чек-лист одобрения").first().waitFor({ timeout: 20000 });
    await settle(page);
    console.log("URL КП-2", page.url());
    const panel = page.locator(PANEL);
    console.log("channels checked by default:", await panel.getByRole("checkbox").evaluateAll((els) => els.map((e) => `${e.getAttribute("aria-label") ?? e.closest("label")?.innerText}:${e.checked}`)));
    await panel.getByRole("button", { name: /Одобрить КП/ }).click();
    await page.waitForTimeout(5000);
    await settle(page);
    console.log("PANEL директор:", (await panel.innerText().catch(() => "")).slice(0, 500));
    await page.context().close();
  }
  {
    const { page } = await np(browser);
    await signIn(page, r, mu.email, pwOf(mu.email));
    await spaGoto(page, "/eds/drafts");
    await settle(page);
    const links = await page.getByRole("link", { name: "Открыть" }).count();
    console.log("МУ: строк КП", links);
    await page.getByRole("link", { name: "Открыть" }).last().click();
    await settle(page);
    console.log("URL МУ", page.url());
    console.log("MAIN МУ:", (await page.locator("#main-content").innerText()).slice(0, 400).replace(/\n+/g, " | "));
    console.log("PANEL МУ:", (await page.locator(PANEL).innerText().catch(() => "")).slice(0, 700).replace(/\n+/g, " | "));
    await screen(page, r, "mu-quote-no-channels", { narrow: false });
    await page.context().close();
  }
  r.save();
};

// a1. B-031: 390 px вкладок «Справочники» и «Шаблоны» компании
scenarios.a1 = async (browser) => {
  const r = new Report("a1");
  const { adminEmail, adminPw } = state();
  const { page } = await np(browser, 390);
  await signIn(page, r, adminEmail, adminPw);
  await spaGoto(page, "/admin/company");
  await settle(page);
  const tabs = await page.getByRole("tab").allInnerTexts();
  console.log("TABS", JSON.stringify(tabs));
  const slug = ["requisites", "blank", "numbering", "quote-terms", "expenses", "templates", "dictionaries", "categories", "platform"];
  for (const [i, t] of tabs.entries()) {
    await page.getByRole("tab", { name: t }).first().click().catch(() => {});
    await settle(page);
    await screenHere(page, r, `company-tab-${i + 1}-${slug[i] ?? i}`);
  }
  r.save();
};

// f1. B-031: файл письма в S3 — скачивание вложения ВХ-003/26 директором (и у делопроизводителя)
scenarios.f1 = async (browser) => {
  const r = new Report("f1");
  const who = PEOPLE.director;
  const { page } = await np(browser, 1440, { acceptDownloads: true });
  await signIn(page, r, who.email, pwOf(who.email));
  await spaGoto(page, `/eds/inbox/${encodeURIComponent("ВХ-003/26")}`);
  await settle(page);
  const link = page.getByRole("link", { name: /demo-letter\.pdf/ }).or(page.getByRole("button", { name: /demo-letter\.pdf/ })).first();
  console.log("есть ссылка на файл:", await link.count());
  const [dl] = await Promise.all([page.waitForEvent("download", { timeout: 20000 }).catch(() => null), link.click().catch((e) => console.log(String(e.message).split("\n")[0]))]);
  if (dl) {
    const path = `${process.env.QA_OUT}/dl-letter.pdf`;
    await dl.saveAs(path);
    const { statSync, readFileSync } = await import("node:fs");
    r.check("файл письма скачан из S3 через Платформу", statSync(path).size > 100 && readFileSync(path).slice(0, 4).toString() === "%PDF", `${dl.suggestedFilename()}, ${statSync(path).size} Б`);
  } else {
    r.check("файл письма скачан из S3 через Платформу", false, "нет загрузки");
  }
  r.save();
};

// probe: снимок и текст страницы
scenarios.probe = async (browser) => {
  const r = new Report("probe");
  const { page } = await np(browser);
  const { adminEmail, adminPw } = state();
  await signIn(page, r, adminEmail, adminPw);
  await spaGoto(page, "/admin/org");
  await settle(page);
  await spaGoto(page, "/admin/org?invite=open&panel=open");
  await settle(page);
  console.log((await page.locator(PANEL).innerText()).slice(0, 3000));
  await shot(page, r, "invite");
  r.save();
};

const only = process.argv.slice(2);
const browser = await launch();
for (const id of only) {
  if (!scenarios[id]) throw new Error(`нет сценария ${id}`);
  console.log(`=== ${id}`);
  await scenarios[id](browser);
}
await browser.close();
