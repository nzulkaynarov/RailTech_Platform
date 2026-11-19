// Сценарий 11. Сотрудник: приглашение → первый вход → второй фактор → замещение → отключение.
import crypto from "node:crypto";
import { execSync } from "node:child_process";
import { PANEL, Report, as, np, obs, seen, settle, spaGoto, state, step } from "./common.mjs";
export const scenarios = {};
const NEW = { name: "Демо Логистова", email: "logist.sc2@demo.example" };

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
/** RFC 6238: 6 цифр, SHA-1, шаг 30 с. */
export function totp(secret, t = Date.now()) {
  const abc = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const c of secret.replace(/[\s=]/g, "").toUpperCase()) { const v = abc.indexOf(c); if (v >= 0) bits += v.toString(2).padStart(5, "0"); }
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)));
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64BE(BigInt(Math.floor(t / 30000)));
  const h = crypto.createHmac("sha1", key).update(buf).digest();
  const o = h[h.length - 1] & 0xf;
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1e6).padStart(6, "0");
}

// 11a. Администратор: «Пригласить сотрудника» по почте — имя, адрес, роль «Снабженец» → письмо.
scenarios["11a"] = async (browser) => {
  const r = new Report("11a");
  const page = await as(browser, r, "admin");
  await spaGoto(page, "/admin/org");
  await settle(page);
  await spaGoto(page, "/admin/org?invite=open&panel=open");
  await settle(page);
  const panel = page.locator(PANEL);
  obs(r, "форма приглашения", { sees: await seen(page, PANEL, 2500) });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/11a-invite-1440.png` });
  const before = mailbox().length;
  await step(page, r, "имя, почта, роль", async () => {
    await panel.getByLabel("Имя и фамилия").fill(NEW.name);
    await panel.getByLabel("Электронная почта").fill(NEW.email);
    await panel.getByRole("checkbox", { name: /^Снабженец/ }).check();
  });
  obs(r, "кнопки формы", { sees: (await buttonsOf(page, PANEL)).join(" | ") });
  await step(page, r, "отправить приглашение", async () => {
    await panel.getByRole("button", { name: /Пригласить|Отправить приглашение|Создать и отправить/ }).last().click();
    await page.waitForTimeout(5000);
    await settle(page);
  });
  const e = (await page.locator(".ant-message:visible, .ant-form-item-explain-error:visible, [role=alert]:visible").allInnerTexts()).join(" | ");
  if (e) obs(r, "сообщения", { sees: e });
  obs(r, "после приглашения", { sees: await seen(page, PANEL, 1500) });
  for (const m of mailbox().slice(0, Math.max(0, mailbox().length - before))) {
    obs(r, `письмо «${m.Subject}»`, { sees: `кому: ${m.To.map((x) => x.Address).join(", ")}\n${mailText(m.ID).text.slice(0, 1200)}` });
  }
  r.save();
};

import { lib, signIn } from "../d26-gate/common.mjs";
// 11b. Новый сотрудник: вход по временному паролю → свой пароль → «Главная» → «Профиль · Безопасность» → код из приложения → повторный вход с кодом.
scenarios["11b"] = async (browser) => {
  const r = new Report("11b");
  const invite = mailbox().find((m) => m.Subject === "Приглашение в Платформу RailTech" && m.To.some((t) => t.Address === NEW.email));
  const temp = /Временный пароль:\s*(\S+)/.exec(invite ? mailText(invite.ID).text : "")?.[1];
  r.check("временный пароль из письма", !!temp);
  const { page } = await np(browser, 1440);
  let pw = "";
  await step(page, r, "первый вход и смена пароля", async () => { pw = await signIn(page, r, NEW.email, temp); });
  obs(r, "«Главная» нового сотрудника", { sees: `${page.url()}\n${await seen(page, "main", 1500)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/11b-home-1440.png` });
  await spaGoto(page, "/me");
  await settle(page);
  await page.getByRole("tab", { name: "Безопасность" }).click().catch(() => {});
  await page.waitForTimeout(1200);
  obs(r, "«Профиль · Безопасность»", { sees: await seen(page, "main", 1500) });
  let key = "";
  await step(page, r, "«Включить» вход с кодом", async () => {
    await page.getByRole("button", { name: "Включить" }).first().click();
    await page.waitForTimeout(2500);
    const box = page.locator("[role=dialog]:visible, main").first();
    const text = await page.locator("[role=dialog]:visible").last().innerText().catch(async () => await seen(page, "main", 3000));
    obs(r, "окно включения", { sees: text.slice(0, 900) });
    key = /введите ключ вручную:\s*([A-Z2-7 ]{16,})/i.exec(text)?.[1]?.replace(/\s/g, "") ?? "";
    r.check("ключ для ручного ввода найден", !!key);
    await page.screenshot({ path: `${process.env.QA_SHOTS}/11b-totp-1440.png` });
    await page.getByLabel("Код из приложения").fill(totp(key));
    await page.getByRole("button", { name: "Подтвердить" }).click();
    await page.waitForTimeout(2500);
  });
  obs(r, "после подтверждения", { sees: (await page.locator("[role=dialog]:visible").last().innerText().catch(() => "")).slice(0, 900) || (await seen(page, "main", 900)) });
  await page.getByRole("button", { name: "Я сохранил коды" }).click().catch(() => {});
  await page.waitForTimeout(1200);
  obs(r, "раздел после включения", { sees: (await seen(page, "main", 2500)).split("Вход с кодом из приложения")[1]?.slice(0, 300) ?? "" });
  await step(page, r, "повторный вход: пароль → код", async () => {
    await page.context().clearCookies();
    await lib.login(page, NEW.email, pw).catch(() => {});
    await page.waitForTimeout(2500);
    obs(r, "после пароля", { sees: `${page.url()}\n${await seen(page, "body", 900)}` });
    const code = page.getByLabel(/Код из приложения|Код/).first();
    await code.fill(totp(key));
    await page.getByRole("button", { name: /Войти|Подтвердить/ }).first().click();
    await page.waitForTimeout(4000);
  });
  obs(r, "после кода", { sees: `${page.url()}\n${await seen(page, "main", 600)}` });
  const s = state();
  const fs = await import("node:fs");
  fs.writeFileSync(`${process.env.QA_OUT}/logist.json`, JSON.stringify({ email: NEW.email, pw, key }));
  r.save();
};

// 11c. Директор: «Профиль · Замещение» → заместитель Демо Универсалов на неделю; задача директору → видна заместителю.
scenarios["11c"] = async (browser) => {
  const r = new Report("11c");
  const page = await as(browser, r, "director");
  await spaGoto(page, "/me");
  await settle(page);
  await page.getByRole("tab", { name: "Замещение" }).click().catch(() => {});
  await page.waitForTimeout(1200);
  obs(r, "«Замещение»", { sees: (await seen(page, "main", 2000)).split("Замещение").slice(-1)[0].slice(0, 700) });
  const dropdown = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option");
  await step(page, r, "кто и даты → «Назначить»", async () => {
    await page.getByRole("combobox", { name: "Кто замещает" }).first().click({ force: true });
    await page.keyboard.type("Универс");
    await page.waitForTimeout(1500);
    obs(r, "кандидаты", { sees: (await dropdown.allInnerTexts()).join(" | ") });
    await dropdown.first().click();
    for (const [label, d] of [["С даты", "19.11.2026"], ["По дату", "26.11.2026"]]) {
      await page.getByLabel(label, { exact: true }).first().click();
      await page.keyboard.type(d);
      await page.keyboard.press("Enter");
      await page.waitForTimeout(400);
    }
    await page.getByRole("button", { name: "Назначить" }).click();
    await page.waitForTimeout(2500);
  });
  const e = (await page.locator(".ant-message:visible, .ant-form-item-explain-error:visible").allInnerTexts()).join(" | ");
  if (e) obs(r, "сообщения", { sees: e });
  obs(r, "после назначения", { sees: (await seen(page, "main", 2000)).split("Замещение").slice(-1)[0].slice(0, 500) });
  // Задача директору: служебка снабженца на согласование.
  const s = await as(browser, r, "supply");
  await spaGoto(s, "/eds/new?type=memo");
  await settle(s);
  const main = s.locator("main");
  await step(s, r, "служебка директору (для проверки замещения)", async () => {
    await main.getByLabel("Тема", { exact: true }).fill("Отпуск без сохранения 25.11.2026");
    for (let i = 0; i < 3; i++) {
      const b = main.getByRole("button", { name: /^Далее/ }).first();
      if (!(await b.isVisible().catch(() => false))) break;
      await b.click();
      await s.waitForTimeout(1200);
      const editor = main.locator("[contenteditable=true]").first();
      if (await editor.isVisible().catch(() => false) && i === 0) { await editor.click(); await s.keyboard.type("Прошу предоставить один день без сохранения заработной платы 25.11.2026."); }
      const area = main.getByLabel("Текст", { exact: true });
      if (await area.isVisible().catch(() => false) && !(await area.inputValue().catch(() => "x"))) await area.fill("Прошу предоставить один день без сохранения заработной платы 25.11.2026.");
    }
    await main.getByRole("button", { name: "Отправить на согласование" }).click();
    await s.waitForTimeout(1500);
    const dlg = s.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) await dlg.getByRole("button").last().click();
    await s.waitForTimeout(3500);
  });
  obs(r, "служебка отправлена", { sees: `${s.url()}\n${(await seen(s, PANEL, 400)) || (await seen(s, "main", 400))}` });
  const m = await as(browser, r, "manager_all");
  await settle(m);
  const text = await seen(m, "main", 3000);
  obs(r, "«Главная» заместителя", { sees: text });
  await m.screenshot({ path: `${process.env.QA_SHOTS}/11c-deputy-home-1440.png` });
  r.save();
};

// 11d. Администратор: отключить Демо Логистову → вход отключённой.
scenarios["11d"] = async (browser) => {
  const r = new Report("11d");
  const page = await as(browser, r, "admin");
  await spaGoto(page, "/admin/org");
  await settle(page);
  await page.getByText(NEW.name).first().click();
  await page.waitForTimeout(2500);
  await settle(page);
  obs(r, "кнопки карточки сотрудника", { sees: (await buttonsOf(page, PANEL)).join(" | ") });
  await step(page, r, "«Отключить»", async () => {
    await page.locator(PANEL).getByRole("button", { name: /Отключить|Заблокировать|Деактивировать/ }).first().click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) {
      obs(r, "окно отключения", { sees: await seen(page, '[role="dialog"]', 1200) });
      await page.screenshot({ path: `${process.env.QA_SHOTS}/11d-disable-1440.png` });
      await dlg.getByRole("button", { name: /Отключить|Заблокировать|Деактивировать/ }).last().click();
    }
    await page.waitForTimeout(3000);
    await settle(page);
  });
  const e = (await page.locator(".ant-message:visible, [role=alert]:visible").allInnerTexts()).join(" | ");
  if (e) obs(r, "сообщения", { sees: e });
  obs(r, "карточка после", { sees: (await seen(page, PANEL, 600)) });
  const fs = await import("node:fs");
  const who = JSON.parse(fs.readFileSync(`${process.env.QA_OUT}/logist.json`, "utf8"));
  const { page: p } = await np(browser, 1440);
  await lib.login(p, who.email, who.pw).catch(() => {});
  await p.waitForTimeout(3000);
  obs(r, "вход отключённой", { sees: `${p.url()}\n${await seen(p, "body", 600)}` });
  r.save();
};

// 11e. Директор: назначить заместителя (повтор 11c без служебки); заместитель — «Главная».
scenarios["11e"] = async (browser) => {
  const r = new Report("11e");
  const page = await as(browser, r, "director");
  await spaGoto(page, "/me");
  await settle(page);
  await page.getByRole("tab", { name: "Замещение" }).click().catch(() => {});
  await page.waitForTimeout(1200);
  const dropdown = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option");
  await step(page, r, "кто и даты → «Назначить»", async () => {
    await page.getByRole("combobox", { name: "Кто замещает" }).first().click({ force: true });
    await page.keyboard.type("Универс");
    await page.waitForTimeout(1500);
    obs(r, "кандидаты", { sees: (await dropdown.allInnerTexts()).join(" | ") });
    await dropdown.filter({ hasText: "Универсалов" }).first().click();
    for (const [suffix, d] of [["-from", "19.11.2026"], ["-to", "26.11.2026"]]) {
      await page.locator(`input[id$="${suffix}"]:visible`).first().click();
      await page.keyboard.type(d);
      await page.keyboard.press("Enter");
      await page.waitForTimeout(400);
    }
    await page.getByRole("button", { name: "Назначить" }).click();
    await page.waitForTimeout(2500);
  });
  const e = (await page.locator(".ant-message:visible, .ant-form-item-explain-error:visible").allInnerTexts()).join(" | ");
  if (e) obs(r, "сообщения", { sees: e });
  obs(r, "после назначения", { sees: (await seen(page, "main", 2500)).split("Безопасность").slice(-1)[0].slice(0, 600) });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/11e-deputy-1440.png` });
  const m = await as(browser, r, "manager_all");
  await settle(m);
  obs(r, "«Главная» заместителя", { sees: await seen(m, "main", 3000) });
  await m.screenshot({ path: `${process.env.QA_SHOTS}/11e-deputy-home-1440.png` });
  r.save();
};

// 11f. Администратор: «Отключить сотрудника» → окно → подтвердить; вход отключённой.
scenarios["11f"] = async (browser) => {
  const r = new Report("11f");
  const page = await as(browser, r, "admin");
  await spaGoto(page, "/admin/org");
  await settle(page);
  await page.getByText(NEW.name).first().click();
  await page.waitForTimeout(2500);
  await settle(page);
  await page.locator(PANEL).getByRole("button", { name: "Отключить сотрудника" }).click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${process.env.QA_SHOTS}/11f-disable-1440.png` });
  obs(r, "подтверждение в карточке", { sees: (await seen(page, PANEL, 6000)).split("Отключить сотрудника").slice(-1)[0].slice(0, 700) });
  const ok = page.locator(PANEL).getByRole("button", { name: "Отключить", exact: true });
  if (await ok.isVisible().catch(() => false)) {
    await step(page, r, "подтвердить отключение", async () => { await ok.click(); await page.waitForTimeout(3000); await settle(page); });
  }
  const e = (await page.locator(".ant-message:visible, [role=alert]:visible").allInnerTexts()).join(" | ");
  if (e) obs(r, "сообщения", { sees: e });
  obs(r, "карточка после", { sees: (await seen(page, PANEL, 300)) });
  const fs = await import("node:fs");
  const who = JSON.parse(fs.readFileSync(`${process.env.QA_OUT}/logist.json`, "utf8"));
  const { page: p } = await np(browser, 1440);
  await lib.login(p, who.email, who.pw).catch(() => {});
  await p.waitForTimeout(3000);
  obs(r, "вход отключённой", { sees: `${p.url()}\n${await seen(p, "body", 600)}` });
  r.save();
};

// 11g. Проверка замещения: задача у директора и у заместителя.
scenarios["11g"] = async (browser) => {
  const r = new Report("11g");
  for (const role of ["director", "manager_all"]) {
    const page = await as(browser, r, role);
    await settle(page);
    const text = await seen(page, "main", 4000);
    const i = text.search(/MEMO-2026\/002|Отпуск без сохранения/);
    obs(r, `${role}: задача по MEMO-2026/002`, { sees: i >= 0 ? text.slice(Math.max(0, i - 150), i + 250) : `нет; ${text.slice(0, 300)}` });
    await page.close();
  }
  r.save();
};
