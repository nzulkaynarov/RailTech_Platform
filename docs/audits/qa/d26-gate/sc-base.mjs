import { screenHere, ADMIN, PEOPLE, PANEL, Report, bff, compose, launch, np, pwOf, saveState, screen, secret, settle, shot, signIn, spaGoto, state, step, toastsGone } from "./common.mjs";
export const scenarios = {};

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
    await page.getByLabel("Название компании").fill("ООО Демо Рельс D26");
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

export const inject = async (uid, text, uname, first = "Азиз") => {
  const n = Date.now() % 2000000000;
  const from = { id: uid, is_bot: false, first_name: first, language_code: "ru", ...(uname ? { username: uname } : {}) };
  const m = { message_id: n % 100000, date: Math.floor(Date.now() / 1000), chat: { id: uid, type: "private" }, from, text };
  if (text.startsWith("/")) m.entities = [{ type: "bot_command", offset: 0, length: text.split(" ")[0].length }];
  const t0 = Date.now();
  await fetch("http://127.0.0.1:18999/_inject", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ update_id: n, message: m }) });
  return t0;
};
export const injectCb = async (uid, data, uname, first) => {
  const n = Date.now() % 2000000000;
  const from = { id: uid, is_bot: false, first_name: first, language_code: "ru", username: uname };
  await fetch("http://127.0.0.1:18999/_inject", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ update_id: n, callback_query: { id: String(n), from, chat_instance: "1", data, message: { message_id: 1, date: Math.floor(Date.now() / 1000), chat: { id: uid, type: "private" }, text: "x" } } }) });
};
