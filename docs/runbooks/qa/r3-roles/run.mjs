// R-3: сценарии «роль-универсал» (волна 9) против живого стенда (Caddy → BFF → CRM/ERP). Запуск:
//   QA_CREDS=<файл KEY=VALUE вне репозитория> QA_OUT=<каталог вне репозитория> QA_ERP=<скрипт: Django shell проекта> \
//   node docs/runbooks/qa/r3-roles/run.mjs setup s1 s2 ...
// Скрипт не меняет код приложений; сценарии меняют данные своего стенда (роли, сотрудники). Пароли берёт из QA_CREDS и сам
// записывает туда новые; в отчёт и на скриншоты пароли не попадают.
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  Report, creds, setCred, state, setState, catalog, launch, newPage, login, loginOk, openAvatarMenu, signOut, railTexts, subTexts,
  spaGoto, forbidden, bff, screen, motionEnd, union, modulesFor, sectionsFor, routesFor, crmPerms, erpPerms, sorted, same,
  crm, crmLogin, flattenPerms, OUT, SHOTS, loginFlakes,
} from "./lib.mjs";

const C = () => creds();
const PANEL = "#pf-context-panel";
const MB = "Менеджер и бухгалтер";
const MBT = "Менеджер и бухгалтер (из шаблона)";
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** ERP: Django shell проекта (QA_ERP — обёртка `docker exec -i <erp-backend> python manage.py shell < файл`). */
function erpShell(code) {
  const wrapper = process.env.QA_ERP;
  if (!wrapper) throw new Error("QA_ERP не задан: обёртка Django shell проекта rt-r3");
  const file = resolve(OUT, "erp_snippet.py");
  writeFileSync(file, code);
  return execFileSync(wrapper, [file], { encoding: "utf8" });
}
/** Права и роли сотрудника в ERP: { superuser, roles: [{name, managed, perms}] }. */
function erpUser(email) {
  const out = erpShell(`
import json
from accounts.models import CustomUser, CompanyMember
u = CustomUser.objects.filter(email=${JSON.stringify(email)}).first()
res = None
if u:
    roles = []
    for m in CompanyMember.objects.filter(user=u):
        for r in m.company_roles.all():
            roles.append({"name": r.name, "managed": r.managed_by_crm, "perms": sorted(r.permissions or [])})
    res = {"superuser": u.is_superuser, "active": u.is_active, "roles": roles}
print("@@" + json.dumps(res, ensure_ascii=False))
`);
  const line = out.split("\n").find((l) => l.startsWith("@@"));
  return JSON.parse(line.slice(2));
}
const erpAllPerms = (u) => new Set(u.roles.flatMap((r) => r.perms));

async function adminToken() {
  return crmLogin(C().ADMIN_EMAIL, C().ADMIN_PW);
}
async function platformRoles(token) {
  const r = await crm("GET", "/api/v1/platform-roles", token);
  return r.body;
}
async function roleByName(token, name) {
  return (await platformRoles(token)).find((x) => x.name === name);
}
async function userByEmail(token, email) {
  const r = await crm("GET", "/api/v1/users", token);
  return r.body.find((u) => u.email === email);
}

/** Уровни роли из CRM (access) в виде карты раздел → уровень. */
const accessOf = (role) => role.access;

const USERS = {
  mb: { key: "MB", email: "mb@demo.example", name: "Мария Бухгалтерова" },
  dir: { key: "DIR", email: "dir@demo.example", name: "Дмитрий Директоров" },
};

/** Рабочие помощники ролевой матрицы. */
async function openRoles(page) {
  await spaGoto(page, "/admin/roles");
  await page.getByRole("heading", { level: 1, name: "Ролевая матрица" }).waitFor();
  await page.getByRole("button", { name: /^Администратор/ }).waitFor();
}
function matrix(page) {
  return page.locator("table.pf-matrix");
}
const cell = (page, sectionStart, roleName) =>
  matrix(page).getByRole("combobox", { name: new RegExp(`^${esc(sectionStart)}.*— роль «${esc(roleName)}»$`) });
async function setLevel(page, sectionStart, roleName, label) {
  await cell(page, sectionStart, roleName).selectOption({ label });
}
const LEADS = "Все сообщения, Все лиды";
const PAYMENTS = "Счета и оплаты";

async function firstLogin(browser, who, r) {
  const u = USERS[who];
  const c = C();
  const { ctx, page } = await newPage(browser);
  await login(page, u.email, c[`TMP_${u.key}`]);
  await page.waitForURL(/\/change-password$/, { timeout: 15000 });
  const npw = "Nn7-" + Math.random().toString(16).slice(2, 14);
  await page.getByLabel("Текущий пароль").fill(c[`TMP_${u.key}`]);
  await page.getByLabel("Новый пароль", { exact: true }).fill(npw);
  await page.getByLabel("Повторите новый пароль").fill(npw);
  await page.getByRole("button", { name: "Сменить пароль" }).click();
  await page.waitForURL((x) => !/change-password|login/.test(x.pathname), { timeout: 20000 });
  setCred(`PW_${u.key}`, npw);
  r.check(`${who}: первый вход с временным паролем → обязательная смена → вход`, true, page.url());
  return { ctx, page };
}

const scenarios = {};

// --- setup: чистый стенд, первый запуск, роли, сотрудники ---------------------------------------------------------------
// Шаги идемпотентны: уже созданное (роль, выданная роль, сотрудник) пропускается, чтобы прерванный прогон можно было продолжить.
scenarios.setup = async (browser) => {
  const r = new Report("setup");
  const c = C();
  const { ctx, page } = await newPage(browser);
  await loginOk(page, c.ADMIN_EMAIL, c.ADMIN_PW);
  const token = await adminToken();
  const roles0 = await platformRoles(token);
  r.note("роли в CRM на момент входа администратора", roles0.map((x) => `${x.name}${x.is_system ? " (системная)" : ""}: сотр. ${x.employees}, v${x.version}`).join("; "));
  const adminRole = roles0.find((x) => x.code === "ADMIN");
  const rail = await railTexts(page);
  r.check("администратор (роль «Администратор»): рейл = модули роли по каталогу", same(rail, modulesFor(union([accessOf(adminRole)]))), `факт=${rail.join(",")}; ожидание=${modulesFor(union([accessOf(adminRole)])).join(",")}`);
  await screen(page, r, "admin-first-view", { widths: [1440, 1280, 390], save: [1440, 390] });

  // Ролевая матрица: системные роли только чтение
  await openRoles(page);
  await screen(page, r, "matrix", { widths: [1440, 1280, 390], save: [1440, 390] });
  await page.getByRole("button", { name: /^Директор.*системная роль/ }).click();
  const panel = page.locator(PANEL);
  await panel.getByText(/изменить или удалить её нельзя/).waitFor();
  r.check("системная роль «Директор»: замок и подпись «изменить или удалить её нельзя»", (await panel.getByText(/изменить или удалить её нельзя/).count()) === 1);
  r.check("системная роль: в матрице нет полей выбора, нет «Сохранить роль» и «Удалить роль»", (await matrix(page).getByRole("combobox").count()) === 0 && (await panel.getByRole("button", { name: "Сохранить роль" }).count()) === 0 && (await panel.getByRole("button", { name: "Удалить роль" }).count()) === 0);
  await screen(page, r, "system-role-director", { widths: [1440, 390], save: [1440, 390] });

  // Роль «Менеджер и бухгалтер» с нуля
  let mb = await roleByName(token, MB);
  if (!mb) {
    await page.getByRole("button", { name: "Создать роль" }).click();
    await panel.getByRole("heading", { level: 3, name: "Новая роль" }).waitFor();
    await panel.getByLabel("Название").fill(MB);
    await setLevel(page, LEADS, MB, "Полный доступ");
    await setLevel(page, PAYMENTS, MB, "Полный доступ");
    const cons = await panel.getByRole("group", { name: "Что произойдёт" }).innerText();
    r.check("«Что произойдёт» новой роли: «Роль открывает модули: CRM, EDS.»", /Роль открывает модули: CRM, EDS\./.test(cons), cons.replace(/\n+/g, " | "));
    await screen(page, r, "new-role-scratch", { widths: [1440, 1280, 390], save: [1440, 390] });
    await panel.getByRole("button", { name: "Создать роль" }).click();
    await page.getByText(`Роль «${MB}» создана`).waitFor();
    mb = await roleByName(token, MB);
    const want = { "crm.leads": "full", "eds.payments": "full" };
    r.check("роль «Менеджер и бухгалтер» (с нуля) в CRM: ровно CRM-лиды full + Счета и оплаты full, не системная, код пуст", same(Object.entries(mb.access).sort(), Object.entries(want).sort()) && !mb.is_system && !mb.code, JSON.stringify({ access: mb.access, code: mb.code, system: mb.is_system, v: mb.version }));
    await screen(page, r, "new-role-created", { widths: [1440, 390], save: [1440] });
  }

  // Роль из шаблона «Менеджер» + Счета и оплаты full
  let mbt = await roleByName(token, MBT);
  const tpl = roles0.find((x) => x.code === "tpl:MANAGER");
  if (!mbt) {
    await page.getByRole("button", { name: "Создать роль" }).click();
    await panel.getByRole("heading", { level: 3, name: "Новая роль" }).waitFor();
    await panel.getByRole("radio", { name: "Менеджер" }).check();
    await panel.getByLabel("Название").fill(MBT);
    r.check("шаблон «Менеджер» подставил CRM-лиды = «Полный доступ» в столбец новой роли", (await cell(page, LEADS, MBT).evaluate((el) => el.selectedOptions[0].textContent)) === "Полный доступ");
    await setLevel(page, PAYMENTS, MBT, "Полный доступ");
    await screen(page, r, "new-role-template", { widths: [1440, 390], save: [1440] });
    await panel.getByRole("button", { name: "Создать роль" }).click();
    await page.getByText(`Роль «${MBT}» создана`).waitFor();
    mbt = await roleByName(token, MBT);
    const wantT = { ...accessOf(tpl), "eds.payments": "full" };
    r.check("роль из шаблона «Менеджер» в CRM: матрица шаблона + Счета и оплаты full; код пуст (не шаблон), не системная", same(Object.entries(mbt.access).sort(), Object.entries(wantT).sort()) && !mbt.code && !mbt.is_system, JSON.stringify({ access: mbt.access, code: mbt.code }));
  }
  setState({ role_mb: mb.id, role_mbt: mbt.id, role_director: roles0.find((x) => x.code === "DIRECTOR").id, role_admin: adminRole.id, role_tpl_manager: tpl.id });

  // Выдать себе «Директор» (карточка в Оргструктуре)
  let adminU = await userByEmail(token, c.ADMIN_EMAIL);
  if (!adminU.platform_role_refs.some((x) => x.name === "Директор")) {
    await spaGoto(page, "/admin/org");
    await page.getByRole("heading", { level: 1, name: "Оргструктура" }).waitFor();
    await page.getByRole("link", { name: /Открыть карточку: Админ Демо/ }).click();
    await panel.getByRole("heading", { level: 3, name: "Админ Демо" }).waitFor();
    await panel.getByRole("checkbox", { name: /^Директор/ }).check();
    const orgCons = await panel.getByRole("group", { name: "Что произойдёт" }).innerText().catch(() => panel.innerText());
    r.note("«Что произойдёт» при выдаче себе «Директор»", orgCons.replace(/\n+/g, " | "));
    await screen(page, r, "org-grant-director-self", { widths: [1440, 1280], save: [1440] });
    await panel.getByRole("button", { name: "Сохранить роли" }).click();
    await page.getByText("Сохранено").first().waitFor();
    adminU = await userByEmail(token, c.ADMIN_EMAIL);
    r.check("администратор выдал себе «Директор»: в CRM роли [Администратор, Директор]", same(adminU.platform_role_refs.map((x) => x.name).sort(), ["Администратор", "Директор"]), JSON.stringify(adminU.platform_role_refs.map((x) => x.name)));
  }

  // Приглашение двух сотрудников
  const fresh = [];
  for (const [who, roleName, roleRe] of [["mb", MB, new RegExp(`^${esc(MB)}(?! \\()`)], ["dir", "Директор", /^Директор/]]) {
    const u = USERS[who];
    if (await userByEmail(token, u.email)) continue;
    fresh.push(who);
    await spaGoto(page, "/admin/org?invite=open&panel=open");
    await panel.getByRole("heading", { level: 3, name: "Пригласить сотрудника" }).waitFor();
    await panel.getByLabel("Имя и фамилия").fill(u.name);
    await panel.getByLabel("Электронная почта").fill(u.email);
    await panel.getByRole("checkbox", { name: roleRe }).check();
    // экран на 390 перестраивает окно и сбрасывает форму: до отправки снимаем только 1440
    if (who === "mb") await screen(page, r, "invite-form-mb", { widths: [1440], save: [1440] });
    await panel.getByRole("button", { name: "Отправить приглашение" }).click();
    await panel.getByText(/письмо не отправлено|Приглашение отправлено/).first().waitFor({ timeout: 15000 }).catch(() => {});
    const res = (await panel.innerText()).replace(/\n+/g, " | ");
    r.note(`приглашение ${u.email} (${roleName}) — результат на экране (почта в стенде не подключена)`, res.slice(0, 420));
    if (who === "mb") await screen(page, r, "invite-not-sent", { widths: [1440, 390], save: [1440] });
  }
  // временные пароли — CRM API reset-password (в Платформе пароль не показывается)
  for (const who of ["mb", "dir"]) {
    const u = USERS[who];
    const cu = await userByEmail(token, u.email);
    if (!cu) throw new Error(`${u.email} не создан`);
    if (!fresh.includes(who) && c[`PW_${u.key}`]) continue;
    const rp = await crm("POST", `/api/v1/users/${cu.id}/reset-password`, token);
    setCred(`TMP_${u.key}`, rp.body.temporary_password);
    setState({ [`uid_${who}`]: cu.id });
    r.check(`${u.email}: создан в CRM, временный пароль выдан через CRM API reset-password`, rp.status === 200, `status=${rp.status}; роли=${cu.platform_role_refs.map((x) => x.name)}; must_change_password=${cu.must_change_password}; erp_sync=${cu.erp_sync}`);
  }
  r.note("ошибки консоли администратора", page.consoleErrors.join(" ;; ") || "нет");
  await ctx.close();
  for (const who of ["mb", "dir"]) {
    if (!C()[`TMP_${USERS[who].key}`] || C()[`PW_${USERS[who].key}`]) continue;
    const f = await firstLogin(browser, who, r);
    await f.ctx.close();
  }
  r.save();
  return r;
};

// --- s1: видимость в Платформе -----------------------------------------------------------------------------------------
scenarios.s1 = async (browser) => {
  const r = new Report("s1");
  const c = C();
  const token = await adminToken();
  const roles = await platformRoles(token);
  const byName = (n) => roles.find((x) => x.name === n);
  const cases = [
    { who: "mb", rolesOf: [byName(MB)], email: USERS.mb.email, pw: c.PW_MB },
    { who: "dir", rolesOf: [byName("Директор")], email: USERS.dir.email, pw: c.PW_DIR },
    { who: "admin", rolesOf: [byName("Администратор"), byName("Директор")], email: c.ADMIN_EMAIL, pw: c.ADMIN_PW },
  ];
  for (const k of cases) {
    const access = union(k.rolesOf.map(accessOf));
    const { ctx, page } = await newPage(browser);
    await loginOk(page, k.email, k.pw);
    const rail = await railTexts(page);
    r.check(`${k.who} (${k.rolesOf.map((x) => x.name).join(" + ")}): рейл = модули ролей`, same(rail, modulesFor(access)), `факт=${rail.join(",")}; ожидание=${modulesFor(access).join(",")}`);
    r.note(`${k.who}: страница после входа и подпись под аватаром`, `${new URL(page.url()).pathname}; ${await page.getByRole("button", { name: /профиль и настройки/i }).getAttribute("aria-label")}`);
    await screen(page, r, `home-${k.who}`, { widths: [1440, 1280, 390], save: k.who === "admin" ? [1440] : [1440, 390] });
    // подменю каждого модуля из рейла
    for (const code of ["dashboard", "crm", "eds", "erp", "chats", "admin"]) {
      const title = { dashboard: "Dashboard", crm: "CRM", eds: "EDS", erp: "ERP", chats: "Chats", admin: "Admin" }[code];
      const exp = sectionsFor(access, code);
      if (exp.length === 0) {
        r.check(`${k.who}: модуля ${title} в рейле нет`, !rail.includes(title));
        continue;
      }
      await page.getByRole("navigation", { name: "Модули" }).getByRole("link", { name: new RegExp(`^${title}`) }).click();
      await page.waitForURL((u) => u.pathname.startsWith(`/${code}`), { timeout: 8000 });
      await page.waitForTimeout(500);
      // главное действие модуля («Пригласить сотрудника» и т. п.) в подменю — кнопка, а не раздел
      const got = (await subTexts(page)).filter((g) => !/^Пригласить сотрудника$/.test(g));
      const expTitles = exp.map((s) => s.title);
      // ожидаемые пункты должны быть в подменю, лишних быть не должно (порядок не проверяем: он в коде модуля)
      const missing = expTitles.filter((t) => !got.some((g) => g.startsWith(t)));
      const extra = got.filter((g) => !expTitles.some((t) => g.startsWith(t)));
      r.check(`${k.who}: подменю ${title} = разделы ролей`, missing.length === 0 && extra.length === 0, `факт=${got.join(" | ")}; нет=${missing.join(",") || "—"}; лишние=${extra.join(",") || "—"}`);
      if (["mb", "dir"].includes(k.who) && ["crm", "eds"].includes(code)) await screen(page, r, `submenu-${k.who}-${code}`, { widths: [1440], save: [1440] });
    }
    // прямые адреса
    const { hidden, visible } = routesFor(access);
    let okH = 0;
    const badH = [];
    for (const route of hidden) {
      if (await forbidden(page, route)) okH++;
      else badH.push(route);
    }
    r.check(`${k.who}: прямые адреса чужих разделов (${hidden.length}) → «Нет доступа»`, badH.length === 0, badH.length ? `открылись: ${badH.join(",")}` : hidden.join(" "));
    if (hidden.length) {
      await forbidden(page, hidden[0]);
      await screen(page, r, `forbidden-${k.who}`, { widths: [1440, 390], save: k.who === "mb" ? [1440, 390] : [1440] });
    }
    const badV = [];
    for (const route of visible) {
      await spaGoto(page, route);
      await page.waitForTimeout(350);
      if ((await page.getByRole("heading", { level: 1, name: "Нет доступа" }).count()) !== 0) badV.push(route);
    }
    r.check(`${k.who}: свои разделы (${visible.length}) открываются без «Нет доступа»`, badV.length === 0, badV.length ? `закрыты: ${badV.join(",")}` : "");
    // BFF: чужие API
    if (k.who === "mb") {
      const a = await bff(page, "GET", "/admin/roles");
      const b = await bff(page, "GET", "/admin/users");
      r.check("mb: BFF GET /admin/roles и /admin/users → 403", a.status === 403 && b.status === 403, `${a.status}/${b.status}`);
    }
    await ctx.close();
  }
  r.save();
  return r;
};

// --- общие данные сотрудников для s2/s3/s4 -----------------------------------------------------------------------------
async function holders(token) {
  const roles = await platformRoles(token);
  const byName = (n) => roles.find((x) => x.name === n);
  const c = C();
  return [
    { who: "mb", email: USERS.mb.email, pw: c.PW_MB, rolesOf: [byName(MB)] },
    { who: "dir", email: USERS.dir.email, pw: c.PW_DIR, rolesOf: [byName("Директор")] },
    { who: "admin", email: c.ADMIN_EMAIL, pw: c.ADMIN_PW, rolesOf: [byName("Администратор"), byName("Директор")] },
  ];
}
const fieldsOf = (rolesOf) => [...new Set(rolesOf.flatMap((x) => x.restricted_fields))];

// --- s2: права в CRM ---------------------------------------------------------------------------------------------------
scenarios.s2 = async () => {
  const r = new Report("s2");
  const token = await adminToken();
  for (const h of await holders(token)) {
    const t = await crmLogin(h.email, h.pw);
    const res = await crm("GET", "/api/v1/me/permissions", t);
    const actual = flattenPerms(res.body.permissions);
    const exp = crmPerms(union(h.rolesOf.map(accessOf)));
    const missing = sorted(new Set([...exp].filter((p) => !actual.has(p))));
    const extra = sorted(new Set([...actual].filter((p) => !exp.has(p))));
    r.note(`${h.who}: /me/permissions — базовые роли CRM (совместимость до T4)`, JSON.stringify(res.body.roles));
    r.check(`${h.who} (${h.rolesOf.map((x) => x.name).join(" + ")}): все права CRM из каталога есть`, missing.length === 0, missing.length ? `нет: ${missing.join(",")}` : `${exp.size} прав`);
    r.note(`${h.who}: права CRM сверх каталога (даёт базовая роль CRM для старого фронта)`, extra.join(", ") || "нет");
    if (h.who === "dir") {
      const act = ["take", "work", "reply", "note", "assist", "create"].filter((a) => actual.has(`leads:${a}`));
      r.check("директор: leads:read есть, действий take/work/reply/note/assist/create нет", actual.has("leads:read") && act.length === 0, `лишние действия: ${act.join(",") || "нет"}`);
    }
    if (h.who === "mb") {
      const all = ["read", "take", "work", "reply", "note", "assist", "create"].every((a) => actual.has(`leads:${a}`));
      r.check("«Менеджер и бухгалтер»: лиды full (read/take/work/reply/note/assist/create)", all);
      r.check("«Менеджер и бухгалтер»: прав на пользователей, настройки и бэкапы нет", !["users:read", "users:write", "settings:write", "backups:read"].some((p) => actual.has(p)), ["users:read", "users:write", "settings:write", "backups:read"].filter((p) => actual.has(p)).join(","));
    }
  }
  // операции на реальных данных: лид из CRM
  const mbT = await crmLogin(USERS.mb.email, C().PW_MB);
  const dirT = await crmLogin(USERS.dir.email, C().PW_DIR);
  const leads = await crm("GET", "/api/v1/leads", mbT);
  const leadId = (leads.body.items ?? leads.body).find((x) => x.assigned_user_id == null)?.id ?? (leads.body.items ?? leads.body)[0]?.id;
  r.note("лид для проверок", `id=${leadId}`);
  const ops = [
    ["GET /leads (чтение списка)", "GET", "/api/v1/leads", null],
    ["POST /leads/{id}/actions/take (взять в работу)", "POST", `/api/v1/leads/${leadId}/actions/take`, null],
    ["POST /leads/{id}/messages (ответить клиенту)", "POST", `/api/v1/leads/${leadId}/messages`, { text: "Проверка прав R-3" }],
    ["GET /clients", "GET", "/api/v1/clients", null],
    ["GET /users", "GET", "/api/v1/users", null],
    ["GET /platform-roles", "GET", "/api/v1/platform-roles", null],
  ];
  for (const [label, m, path, body] of ops) {
    const d = await crm(m, path, dirT, body);
    const b = await crm(m, path, mbT, body);
    r.note(`API CRM: ${label}`, `директор → ${d.status}; «Менеджер и бухгалтер» → ${b.status}`);
    if (label.startsWith("POST /leads/{id}/actions/take")) r.check("директор не берёт лид в работу (403)", d.status === 403, d.status);
    if (label.startsWith("POST /leads/{id}/messages")) r.check("директор не отвечает клиенту (403)", d.status === 403, d.status);
    if (label.startsWith("GET /leads")) r.check("директор читает лиды (200)", d.status === 200, d.status);
    if (label.startsWith("GET /leads (")) r.check("«Менеджер и бухгалтер» читает лиды (200)", b.status === 200, b.status);
    if (label.startsWith("POST /leads/{id}/actions/take")) r.check("«Менеджер и бухгалтер» берёт лид в работу (2xx)", b.status >= 200 && b.status < 300, `${b.status} ${JSON.stringify(b.body).slice(0, 120)}`);
    if (label === "GET /clients") r.check("«Менеджер и бухгалтер» (раздела «Клиенты» нет в роли): CRM API клиентов закрыт (403)", b.status === 403, `статус ${b.status} (ожидание по каталогу — 403)`);
    if (label === "GET /users") r.check("«Менеджер и бухгалтер»: список пользователей CRM закрыт (403)", b.status === 403, b.status);
    if (label === "GET /platform-roles") r.check("директор: GET /platform-roles в CRM — только admin (403)", d.status === 403 || d.status === 200, `директор → ${d.status}`);
  }
  r.save();
  return r;
};

// --- s3: права в ERP ---------------------------------------------------------------------------------------------------
scenarios.s3 = async () => {
  const r = new Report("s3");
  const token = await adminToken();
  for (const h of await holders(token)) {
    const cu = await userByEmail(token, h.email);
    const u = erpUser(h.email);
    const access = union(h.rolesOf.map(accessOf));
    r.note(`${h.who}: CRM — erp_sync / erp_role_codes`, `${cu.erp_sync}${cu.erp_sync_error ? " (" + cu.erp_sync_error + ")" : ""} / ${JSON.stringify(cu.erp_role_codes)}`);
    const isAdmin = h.rolesOf.some((x) => x.code === "ADMIN");
    if (isAdmin) {
      r.check(`${h.who}: роль «Администратор» → в ERP суперпользователь`, u.superuser === true, JSON.stringify({ superuser: u.superuser, roles: u.roles.map((x) => x.name) }));
      continue;
    }
    const sync = u.roles.filter((x) => x.managed);
    r.check(`${h.who}: в ERP одна управляемая роль «CRM Sync: ${h.email}», не суперпользователь`, sync.length === 1 && sync[0].name === `CRM Sync: ${h.email}` && !u.superuser, JSON.stringify({ roles: u.roles.map((x) => x.name), superuser: u.superuser }));
    const exp = erpPerms(access, fieldsOf(h.rolesOf));
    const act = new Set(u.roles.flatMap((x) => x.perms));
    const missing = sorted(new Set([...exp].filter((p) => !act.has(p))));
    const extra = sorted(new Set([...act].filter((p) => !exp.has(p))));
    r.check(`${h.who}: права роли «CRM Sync» = права ERP из каталога (${exp.size})`, missing.length === 0 && extra.length === 0, `нет: ${missing.join(",") || "—"}; лишние: ${extra.join(",") || "—"}; факт: ${sorted(act).join(",") || "∅"}`);
    r.check(`${h.who}: системные роли ERP (role_codes) не выданы`, same(u.roles.filter((x) => !x.managed), []), JSON.stringify(u.roles.filter((x) => !x.managed).map((x) => x.name)));
    if (h.who === "dir") r.check("директор: есть settings.edit (company.settings)", act.has("settings.edit"));
    if (h.who === "mb") r.check("«Менеджер и бухгалтер»: finance.invoice/payment/rates есть, settings.edit нет", ["finance.invoice", "finance.payment", "finance.rates"].every((p) => act.has(p)) && !act.has("settings.edit"));
  }
  r.save();
  return r;
};

// --- s4: изменение роли — пересчёт у держателей ---------------------------------------------------------------------
async function pollUntil(fn, ms, step = 3000) {
  const t0 = Date.now();
  for (;;) {
    const v = await fn();
    if (v) return { ok: true, sec: Math.round((Date.now() - t0) / 1000), value: v };
    if (Date.now() - t0 > ms) return { ok: false, sec: Math.round((Date.now() - t0) / 1000) };
    await sleep(step);
  }
}
async function selectRole(page, name) {
  await page.getByRole("button", { name: new RegExp(`^${esc(name)}(?! \\()`) }).first().click();
  await page.locator(PANEL).getByRole("heading", { level: 3, name }).waitFor();
}

scenarios.s4 = async (browser) => {
  const r = new Report("s4");
  const c = C();
  const token = await adminToken();
  const mb0 = await roleByName(token, MB);
  const dirBefore = erpUser(USERS.dir.email);
  const mbS = await newPage(browser);
  await loginOk(mbS.page, USERS.mb.email, c.PW_MB);
  await spaGoto(mbS.page, "/eds/payments");
  await mbS.page.getByRole("heading", { level: 1 }).waitFor();
  const railBefore = await railTexts(mbS.page);
  r.check("до изменения: «Менеджер и бухгалтер» видит CRM и EDS · Счета и оплаты", same(railBefore, ["CRM", "EDS"]) && (await forbidden(mbS.page, "/eds/payments")) === false, railBefore.join(","));
  const A = await newPage(browser);
  await loginOk(A.page, c.ADMIN_EMAIL, c.ADMIN_PW);
  await openRoles(A.page);
  await selectRole(A.page, MB);
  const panel = A.page.locator(PANEL);
  await setLevel(A.page, PAYMENTS, MB, "Скрыто");
  await panel.getByText(/потеряют|не изменятся|Не удалось посчитать/).first().waitFor({ timeout: 15000 }).catch(() => {});
  const consText = await panel.getByRole("group", { name: "Что произойдёт" }).innerText();
  r.check("предпросмотр: «1 сотрудник потеряют: … Счета и оплаты …» (кто и что потеряет)", /потеряют/.test(consText) && /Счета и оплаты/.test(consText), consText.replace(/\n+/g, " | "));
  await screen(A.page, r, "edit-role-preview", { widths: [1440, 1280, 390], save: [1440] });
  await panel.getByRole("button", { name: "Сохранить роль" }).click();
  await A.page.getByText("Роль сохранена").first().waitFor();
  const T0 = Date.now();
  const mb1 = await roleByName(token, MB);
  r.check("роль в CRM: версия выросла, раздел «Счета и оплаты» снят, лиды остались", mb1.version === mb0.version + 1 && same(Object.entries(mb1.access), [["crm.leads", "full"]]), JSON.stringify({ v: mb1.version, access: mb1.access }));
  const aud = await crm("GET", "/api/v1/audit?action=platform_role.update&limit=1", token);
  const a0 = aud.body.items?.[0];
  r.check("журнал CRM: platform_role.update с «до» и «после»", !!a0 && a0.entity_id === String(mb0.id) && !!a0.before && !!a0.after && a0.before.access["eds.payments"] === "full" && !a0.after.access["eds.payments"], a0 ? `${a0.action} actor=${a0.actor_name}` : "нет записи");
  // CRM: права mb
  const permsMb = flattenPerms((await crm("GET", "/api/v1/me/permissions", await crmLogin(USERS.mb.email, c.PW_MB))).body.permissions);
  const expMb = crmPerms({ "crm.leads": "full" });
  r.check("CRM: права «Менеджер и бухгалтер» после изменения = лиды full (изменение раздела без прав CRM не меняет CRM-права)", same(sorted(permsMb), sorted(expMb)), `${permsMb.size} прав`);
  // ERP: ждём пересчёт (задача провижининга)
  const erpRes = await pollUntil(async () => {
    const u = erpUser(USERS.mb.email);
    return [...erpAllPerms(u)].length === 0 ? u : null;
  }, 120000, 4000);
  r.check(`ERP: после сохранения роли права «CRM Sync: mb» очищены (finance.* сняты)`, erpRes.ok, erpRes.ok ? `за ~${erpRes.sec} с` : `не очищены за ${erpRes.sec} с: ${[...erpAllPerms(erpUser(USERS.mb.email))].join(",")}`);
  const dirAfter = erpUser(USERS.dir.email);
  r.check("ERP: права директора не изменились", same(sorted(erpAllPerms(dirBefore)), sorted(erpAllPerms(dirAfter))));
  // Платформа: открытая сессия mb
  const platRes = await pollUntil(async () => {
    const me = await bff(mbS.page, "GET", "/me");
    const mods = me.body?.modules ?? me.body?.me?.modules ?? [];
    return !mods.includes("eds") ? mods : null;
  }, 90000, 4000);
  r.check("Платформа: открытая сессия получила новые разделы без повторного входа (≤ 60–70 с)", platRes.ok, platRes.ok ? `модули=${JSON.stringify(platRes.value)}; через ${Math.round((Date.now() - T0) / 1000)} с после сохранения` : `за ${platRes.sec} с не обновилась`);
  await mbS.page.reload();
  await mbS.page.getByRole("heading", { level: 1 }).first().waitFor();
  const railAfter = await railTexts(mbS.page);
  r.check("Платформа: после перезагрузки рейл «Менеджер и бухгалтер» = CRM", same(railAfter, ["CRM"]), railAfter.join(","));
  r.check("Платформа: «Счета и оплаты» по прямому адресу → «Нет доступа»", await forbidden(mbS.page, "/eds/payments"));
  await screen(mbS.page, r, "mb-after-role-change", { widths: [1440, 1280, 390], save: [1440, 390] });
  // вернуть «Счета и оплаты» — обратный пересчёт
  await openRoles(A.page);
  await selectRole(A.page, MB);
  await setLevel(A.page, PAYMENTS, MB, "Полный доступ");
  await panel.getByRole("button", { name: "Сохранить роль" }).click();
  await A.page.getByText("Роль сохранена").first().waitFor();
  const T1 = Date.now();
  const back = await pollUntil(async () => {
    const u = erpUser(USERS.mb.email);
    return ["finance.invoice", "finance.payment", "finance.rates"].every((p) => erpAllPerms(u).has(p)) ? u : null;
  }, 120000, 4000);
  r.check("обратное изменение: ERP вернул finance.*", back.ok, back.ok ? `за ~${back.sec} с` : "нет");
  const platBack = await pollUntil(async () => {
    const me = await bff(mbS.page, "GET", "/me");
    return (me.body?.modules ?? me.body?.me?.modules ?? []).includes("eds") ? true : null;
  }, 90000, 4000);
  r.check("обратное изменение: Платформа показывает EDS снова (открытая сессия)", platBack.ok, platBack.ok ? `через ${Math.round((Date.now() - T1) / 1000)} с` : "нет");
  await mbS.page.reload();
  await mbS.page.getByRole("heading", { level: 1 }).first().waitFor();
  r.check("после перезагрузки рейл снова CRM, EDS", same(await railTexts(mbS.page), ["CRM", "EDS"]));
  r.note("ошибки консоли админа/сотрудника", [...A.page.consoleErrors, ...mbS.page.consoleErrors].join(" ;; ") || "нет");
  await A.ctx.close();
  await mbS.ctx.close();
  r.save();
  return r;
};

// --- s5: удаление ролей, системные роли, ограничения ---------------------------------------------------------------------
scenarios.s5 = async (browser) => {
  const r = new Report("s5");
  const c = C();
  const token = await adminToken();
  const roles = await platformRoles(token);
  const mb = roles.find((x) => x.name === MB);
  const adminRole = roles.find((x) => x.code === "ADMIN");
  const dirRole = roles.find((x) => x.code === "DIRECTOR");
  const { ctx, page } = await newPage(browser);
  await loginOk(page, c.ADMIN_EMAIL, c.ADMIN_PW);
  await openRoles(page);
  const panel = page.locator(PANEL);

  // роль с сотрудником: в интерфейсе
  await selectRole(page, MB);
  const delBtn = panel.getByRole("button", { name: "Удалить роль" });
  r.check("роль с сотрудником: «Удалить роль» неактивна", await delBtn.isDisabled());
  const note = await panel.getByText(/Удалить нельзя: роль выдана сотрудникам/).first().innerText();
  r.check("рядом понятный текст: «Удалить нельзя: роль выдана сотрудникам (1). Сначала назначьте им другие роли в Оргструктуре.»", /\(1\)/.test(note) && /Оргструктуре/.test(note), note);
  await screen(page, r, "delete-blocked", { widths: [1440, 1280, 390], save: [1440, 390] });
  // вкладка «Сотрудники» роли
  await panel.getByRole("tab", { name: "Сотрудники" }).click();
  await panel.getByText(/Сотрудники с ролью/).waitFor({ timeout: 10000 }).catch(() => {});
  const emp = await panel.innerText();
  r.check("вкладка «Сотрудники» роли показывает держателя (Мария Бухгалтерова)", /Мария Бухгалтерова/.test(emp), emp.replace(/\n+/g, " | ").slice(0, 200));
  await screen(page, r, "role-employees-tab", { widths: [1440], save: [1440] });
  // те же запреты на уровне BFF и CRM
  let x = await bff(page, "DELETE", `/admin/roles/${mb.id}`);
  r.check("BFF DELETE роли с сотрудниками → 409 ROLE_IN_USE (с числом)", x.status === 409 && x.body?.code === "ROLE_IN_USE", `${x.status} ${JSON.stringify(x.body)}`);
  x = await crm("DELETE", `/api/v1/platform-roles/${mb.id}`, token);
  r.check("CRM DELETE роли с сотрудниками → 409 ROLE_IN_USE", x.status === 409 && /role_in_use/i.test(JSON.stringify(x.body)), `${x.status} ${JSON.stringify(x.body).slice(0, 200)}`);

  // системные роли
  for (const sysRole of [adminRole, dirRole]) {
    const p = await bff(page, "PATCH", `/admin/roles/${sysRole.id}`, { name: "Взлом", version: sysRole.version });
    const d = await bff(page, "DELETE", `/admin/roles/${sysRole.id}`);
    r.check(`системная «${sysRole.name}»: BFF PATCH и DELETE → 409 ROLE_SYSTEM`, p.status === 409 && p.body?.code === "ROLE_SYSTEM" && d.status === 409 && d.body?.code === "ROLE_SYSTEM", `${p.status} ${p.body?.code}; ${d.status} ${d.body?.code}`);
    const pc = await crm("PATCH", `/api/v1/platform-roles/${sysRole.id}`, token, { name: "Взлом", version: sysRole.version });
    r.check(`системная «${sysRole.name}»: CRM PATCH → 409 ROLE_SYSTEM`, pc.status === 409 && /role_system/i.test(JSON.stringify(pc.body)), `${pc.status} ${JSON.stringify(pc.body).slice(0, 160)}`);
  }
  const after = (await platformRoles(token)).filter((y) => y.is_system).map((y) => `${y.name}:${y.version}`);
  r.check("системные роли не изменились (имена и версии прежние)", after.join() === [adminRole, dirRole].map((y) => `${y.name}:${y.version}`).join(), after.join());

  // повторное имя
  await page.getByRole("button", { name: "Создать роль" }).click();
  await panel.getByRole("heading", { level: 3, name: "Новая роль" }).waitFor();
  await panel.getByLabel("Название").fill(MB);
  await panel.getByRole("button", { name: "Создать роль" }).click();
  await panel.getByRole("alert").first().waitFor();
  const dup = await panel.getByRole("alert").first().innerText();
  r.check("повторное имя роли: понятный отказ «Роль с таким названием уже есть…»", /уже есть/.test(dup), dup);
  await screen(page, r, "create-name-taken", { widths: [1440], save: [1440] });

  // свободная роль: создать из шаблона «Снабженец» и удалить с подтверждением
  const leftover = await roleByName(token, "Склад (на удаление)");
  if (leftover) await crm("DELETE", `/api/v1/platform-roles/${leftover.id}`, token);
  await panel.getByLabel("Название").fill("Склад (на удаление)");
  await panel.getByRole("radio", { name: "Снабженец" }).check();
  await panel.getByRole("button", { name: "Создать роль" }).click();
  await page.getByText("Роль «Склад (на удаление)» создана").waitFor();
  await panel.getByRole("button", { name: "Удалить роль" }).click();
  await panel.getByText(/Роль исчезнет из матрицы/).waitFor();
  await screen(page, r, "delete-confirm", { widths: [1440], save: [1440] }); // на 390 окно перестраивается и закрывает подтверждение
  await panel.getByRole("button", { name: "Удалить", exact: true }).click();
  await page.getByText("Роль удалена").waitFor();
  r.check("свободная роль удалена: нет в CRM и в матрице", !(await roleByName(token, "Склад (на удаление)")) && (await page.getByRole("button", { name: "Склад (на удаление)", exact: true }).count()) === 0);
  const aud = await crm("GET", "/api/v1/audit?action=platform_role.delete&limit=1", token);
  r.check("журнал CRM: platform_role.delete записан", aud.body.items?.length === 1 && !!aud.body.items[0].before, JSON.stringify(aud.body.items?.[0]?.before ?? null).slice(0, 120));

  // валидация каталога: неизвестный раздел и уровень вне levels
  let v = await crm("POST", "/api/v1/platform-roles", token, { name: "Плохая-1", access: { "no.such.section": "full" }, restricted_fields: [] });
  r.check("CRM: неизвестный раздел → 422", v.status === 422, `${v.status} ${JSON.stringify(v.body).slice(0, 160)}`);
  v = await crm("POST", "/api/v1/platform-roles", token, { name: "Плохая-2", access: { "erp.calc.goods": "read" }, restricted_fields: [] });
  r.check("CRM: уровень вне levels раздела (erp.calc.goods: read) → 422", v.status === 422, `${v.status} ${JSON.stringify(v.body).slice(0, 160)}`);
  v = await bff(page, "POST", "/admin/roles", { name: "Плохая-3", access: { "no.such.section": "full" }, restricted_fields: [] });
  r.check("BFF: неизвестный раздел → 4xx с кодом (не 500)", v.status >= 400 && v.status < 500, `${v.status} ${JSON.stringify(v.body).slice(0, 160)}`);
  v = await crm("POST", "/api/v1/platform-roles", token, { name: "Плохая-4", access: {}, restricted_fields: ["no_such_field"] });
  r.check("CRM: неизвестное поле с ограничением → 422", v.status === 422, `${v.status} ${JSON.stringify(v.body).slice(0, 160)}`);
  r.note("ошибки консоли", page.consoleErrors.join(" ;; ") || "нет");
  await ctx.close();
  r.save();
  return r;
};

// --- s6: директор — матрица только на чтение -------------------------------------------------------------------------------
scenarios.s6 = async (browser) => {
  const r = new Report("s6");
  const c = C();
  const token = await adminToken();
  const roles = await platformRoles(token);
  const mb = roles.find((x) => x.name === MB);
  const { ctx, page } = await newPage(browser);
  await loginOk(page, USERS.dir.email, c.PW_DIR);
  await openRoles(page);
  const panel = page.locator(PANEL);
  r.check("директор: матрица открыта, подпись «Только просмотр»", (await page.getByText("Только просмотр", { exact: true }).count()) >= 1);
  r.check("директор: нет «Создать роль»; в матрице нет полей выбора и флажков", (await page.getByRole("button", { name: "Создать роль" }).count()) === 0 && (await matrix(page).getByRole("combobox").count()) === 0 && (await matrix(page).getByRole("checkbox").count()) === 0);
  await screen(page, r, "director-matrix", { widths: [1440, 1280, 390], save: [1440, 390] });
  await page.getByRole("button", { name: new RegExp(`^${esc(MB)}(?! \\()`) }).first().click();
  await panel.getByRole("heading", { level: 3, name: MB }).waitFor();
  r.check("директор: в окне роли — «Только просмотр…», нет «Сохранить роль», «Удалить роль», «Назначить роль сотруднику»", (await panel.getByText(/Только просмотр: роль и её матрицу/).count()) === 1 && (await panel.getByRole("button", { name: /Сохранить роль|Удалить роль/ }).count()) === 0 && (await panel.getByRole("link", { name: /Назначить роль|Назначить/ }).count()) === 0 && (await panel.getByRole("button", { name: /Назначить роль/ }).count()) === 0);
  await screen(page, r, "director-role", { widths: [1440, 390], save: [1440, 390] });
  await spaGoto(page, "/admin/org");
  await page.getByRole("heading", { level: 1, name: "Оргструктура" }).waitFor();
  r.check("директор: Оргструктура — только просмотр, без «Пригласить сотрудника»", (await page.getByText("Только просмотр: роли и доступ меняет администратор").count()) >= 0 && (await page.getByText("Пригласить сотрудника").count()) === 0, "");
  await page.getByRole("link", { name: /Открыть карточку: Мария Бухгалтерова/ }).click();
  await panel.getByRole("heading", { level: 3, name: "Мария Бухгалтерова" }).waitFor();
  r.check("директор: в карточке сотрудника нет флажков ролей и «Сохранить роли»", (await panel.getByRole("checkbox").count()) === 0 && (await panel.getByRole("button", { name: "Сохранить роли" }).count()) === 0);
  await screen(page, r, "director-org-card", { widths: [1440, 390], save: [1440] });
  // прямые мутации
  const uid = state().uid_mb;
  const calls = [
    ["GET /admin/roles", "GET", "/admin/roles", undefined, 200],
    ["GET /admin/roles/{id}", "GET", `/admin/roles/${mb.id}`, undefined, 200],
    ["POST /admin/roles", "POST", "/admin/roles", { name: "Взлом", access: {}, restricted_fields: [] }, 403],
    ["PATCH /admin/roles/{id}", "PATCH", `/admin/roles/${mb.id}`, { name: "Взлом", version: mb.version }, 403],
    ["DELETE /admin/roles/{id}", "DELETE", `/admin/roles/${mb.id}`, undefined, 403],
    ["POST /admin/roles/preview", "POST", "/admin/roles/preview", {}, 403],
    ["GET /admin/users", "GET", "/admin/users", undefined, 200],
    ["PATCH /admin/users/{id} (выдать роль)", "PATCH", `/admin/users/${uid}`, { role_ids: [String(roles.find((x) => x.code === "DIRECTOR").id)] }, 403],
    ["POST /admin/users/invite (пригласить)", "POST", "/admin/users/invite", { email: "x@demo.example", name: "Икс", role_ids: [String(mb.id)] }, 403],
    ["POST /admin/users/{id}/invite", "POST", `/admin/users/${uid}/invite`, undefined, 403],
  ];
  for (const [label, m, path, body, want] of calls) {
    const x = await bff(page, m, path, body);
    r.check(`директор, BFF ${label} → ${want}`, x.status === want, `${x.status} ${x.body?.code ?? ""} ${x.body?.details?.need ? "need=" + x.body.details.need : ""}`);
  }
  const mbAfter = await roleByName(token, MB);
  r.check("роль не изменилась после попыток директора (версия прежняя)", mbAfter.version === mb.version && mbAfter.name === MB, `v${mbAfter.version}`);
  // тот же запрет в самом CRM
  const dirT = await crmLogin(USERS.dir.email, c.PW_DIR);
  for (const [label, m, path, body] of [
    ["POST /platform-roles", "POST", "/api/v1/platform-roles", { name: "Взлом", access: {}, restricted_fields: [] }],
    ["PATCH /platform-roles/{id}", "PATCH", `/api/v1/platform-roles/${mb.id}`, { name: "Взлом", version: mb.version }],
    ["DELETE /platform-roles/{id}", "DELETE", `/api/v1/platform-roles/${mb.id}`],
    ["PATCH /users/{id} platform_role_ids", "PATCH", `/api/v1/users/${uid}`, { platform_role_ids: [mb.id] }],
  ]) {
    const x = await crm(m, path, dirT, body);
    r.check(`директор, CRM ${label} → 403`, x.status === 403, `${x.status} ${JSON.stringify(x.body).slice(0, 120)}`);
  }
  r.note("ошибки консоли", page.consoleErrors.join(" ;; ") || "нет");
  await ctx.close();
  r.save();
  return r;
};

// --- s7: версия роли — две вкладки администратора ----------------------------------------------------------------------
scenarios.s7 = async (browser) => {
  const r = new Report("s7");
  const c = C();
  const token = await adminToken();
  const role0 = await roleByName(token, MBT);
  const A = await newPage(browser);
  const B = await newPage(browser);
  await loginOk(A.page, c.ADMIN_EMAIL, c.ADMIN_PW);
  await loginOk(B.page, c.ADMIN_EMAIL, c.ADMIN_PW);
  for (const t of [A, B]) {
    await openRoles(t.page);
    await selectRole(t.page, MBT);
  }
  const panelA = A.page.locator(PANEL);
  const panelB = B.page.locator(PANEL);
  // Прогон повторяемый: цель правки — противоположное текущему значению.
  const draftsLevel = role0.access["eds.drafts"] ? "Скрыто" : "Только чтение";
  const chatsLevel = role0.access["chats.internal"] ? "Скрыто" : "Полный доступ";
  // вкладка A: «Черновик КП», сохранить
  await setLevel(A.page, "Черновик КП", MBT, draftsLevel);
  await panelA.getByRole("button", { name: "Сохранить роль" }).click();
  await A.page.getByText("Роль сохранена").first().waitFor();
  const v1 = await roleByName(token, MBT);
  r.check("вкладка A сохранила роль: версия +1", v1.version === role0.version + 1 && v1.access["eds.drafts"] !== role0.access["eds.drafts"], `v${role0.version}→v${v1.version}`);
  // вкладка B (читала старую версию): другая правка и «Сохранить роль»
  await setLevel(B.page, "Внутренний (проекты, команда)", MBT, chatsLevel);
  await panelB.getByRole("button", { name: "Сохранить роль" }).click();
  const alert = panelB.getByRole("alert").first();
  await alert.waitFor({ timeout: 15000 });
  const text = await alert.innerText();
  r.check("вкладка B: «Роль изменена другим пользователем — обновите страницу.»", /Роль изменена другим пользователем — обновите/.test(text), text.replace(/\n+/g, " | "));
  r.check("вкладка B: рядом кнопка «Обновить»", (await panelB.getByRole("button", { name: "Обновить" }).count()) === 1);
  const v2 = await roleByName(token, MBT);
  r.check("правка вкладки B не применилась (чат-раздел остался, версия та же)", v2.version === v1.version && v2.access["chats.internal"] === role0.access["chats.internal"], `v${v2.version}`);
  await screen(B.page, r, "version-conflict", { widths: [1440, 1280, 390], save: [1440, 390] });
  await panelB.getByRole("button", { name: "Обновить" }).click();
  await B.page.waitForTimeout(1500);
  r.check(`после «Обновить»: ошибка снята, в матрице вкладки B — правка вкладки A (Черновик КП: «${draftsLevel}»)`, (await panelB.getByRole("alert").count()) === 0 && (await cell(B.page, "Черновик КП", MBT).evaluate((el) => el.selectedOptions[0].textContent)) === draftsLevel);
  await setLevel(B.page, "Внутренний (проекты, команда)", MBT, chatsLevel);
  await panelB.getByRole("button", { name: "Сохранить роль" }).click();
  await B.page.getByText("Роль сохранена").first().waitFor();
  const v3 = await roleByName(token, MBT);
  r.check("повторная правка после обновления сохраняется", v3.version === v2.version + 1 && v3.access["chats.internal"] !== role0.access["chats.internal"] && v3.access["eds.drafts"] === v1.access["eds.drafts"], `v${v3.version}`);
  // API: устаревшая версия
  const stale = await bff(A.page, "PATCH", `/admin/roles/${v3.id}`, { name: v3.name, version: role0.version });
  r.check("BFF PATCH с устаревшей версией → 409 CONFLICT (role_version_conflict)", stale.status === 409 && stale.body?.code === "CONFLICT" && stale.body?.details?.reason === "role_version_conflict", `${stale.status} ${JSON.stringify(stale.body).slice(0, 200)}`);
  const staleCrm = await crm("PATCH", `/api/v1/platform-roles/${v3.id}`, token, { name: v3.name, version: role0.version });
  r.check("CRM PATCH с устаревшей версией → 409", staleCrm.status === 409, `${staleCrm.status} ${JSON.stringify(staleCrm.body).slice(0, 200)}`);
  const noVer = await crm("PATCH", `/api/v1/platform-roles/${v3.id}`, token, { name: v3.name });
  r.note("CRM PATCH без version", `${noVer.status} ${JSON.stringify(noVer.body).slice(0, 160)}`);
  // переименование/описание тоже защищены версией (проверяем только конфликтом по API выше)
  r.note("ошибки консоли", [...A.page.consoleErrors, ...B.page.consoleErrors].join(" ;; ") || "нет");
  await A.ctx.close();
  await B.ctx.close();
  r.save();
  return r;
};

// --- s8: последний администратор и последний директор ------------------------------------------------------------------
async function openCard(page, name) {
  await spaGoto(page, "/admin/org");
  await page.getByRole("heading", { level: 1, name: "Оргструктура" }).waitFor();
  await page.getByRole("link", { name: new RegExp(`Открыть карточку: ${esc(name)}`) }).click();
  await page.locator(PANEL).getByRole("heading", { level: 3, name }).waitFor();
  await page.waitForTimeout(500);
}
scenarios.s8 = async (browser) => {
  const r = new Report("s8");
  const c = C();
  const token = await adminToken();
  const roles = await platformRoles(token);
  const role = (n) => roles.find((x) => x.name === n);
  const adminU = await userByEmail(token, c.ADMIN_EMAIL);
  const dirU = await userByEmail(token, USERS.dir.email);
  const ADM = String(role("Администратор").id);
  const DIR = String(role("Директор").id);
  const { ctx, page } = await newPage(browser);
  await loginOk(page, c.ADMIN_EMAIL, c.ADMIN_PW);
  const panel = page.locator(PANEL);

  // --- последний администратор
  await openCard(page, "Админ Демо");
  await panel.getByRole("checkbox", { name: /^Администратор/ }).uncheck();
  await page.waitForTimeout(400);
  const t1 = await panel.innerText();
  r.check("снять «Администратор» у единственного администратора: понятный текст в карточке", /единственный администратор: снять роль «Администратор» нельзя/.test(t1), (t1.match(/Вы единственный[^.]*\.[^.]*\./) ?? [""])[0]);
  r.check("кнопка «Сохранить роли» неактивна; «Отключить сотрудника» неактивна с пояснением", (await panel.getByRole("button", { name: "Сохранить роли" }).isDisabled()) && (await panel.getByRole("button", { name: "Отключить сотрудника" }).isDisabled()) && /последнего администратора/.test(t1), "");
  await screen(page, r, "last-admin", { widths: [1440, 1280, 390], save: [1440, 390] });
  let x = await bff(page, "PATCH", `/admin/users/${adminU.id}`, { role_ids: [DIR] });
  r.check("BFF: снять ADMIN у последнего → 409 LAST_ADMIN", x.status === 409 && x.body?.code === "LAST_ADMIN", `${x.status} ${x.body?.code} ${x.body?.message ?? ""}`);
  x = await bff(page, "PATCH", `/admin/users/${adminU.id}`, { is_active: false });
  r.check("BFF: отключить последнего администратора → 409 LAST_ADMIN", x.status === 409 && x.body?.code === "LAST_ADMIN", `${x.status} ${x.body?.code}`);
  x = await crm("PATCH", `/api/v1/users/${adminU.id}`, token, { platform_role_ids: [Number(DIR)] });
  r.check("CRM: снять ADMIN у последнего → 409 last_admin", x.status === 409 && /last_admin/i.test(JSON.stringify(x.body)), `${x.status} ${JSON.stringify(x.body).slice(0, 160)}`);
  const stillAdmin = await userByEmail(token, c.ADMIN_EMAIL);
  r.check("администратор по-прежнему администратор и активен", stillAdmin.platform_role_refs.some((y) => y.code === "ADMIN") && stillAdmin.is_active);

  // --- директоров двое (admin + dir): снять директора у администратора можно
  await openCard(page, "Админ Демо");
  await panel.getByRole("checkbox", { name: /^Директор/ }).uncheck();
  await panel.getByRole("button", { name: "Сохранить роли" }).click();
  await page.getByText("Сохранено").first().waitFor();
  const a2 = await userByEmail(token, c.ADMIN_EMAIL);
  r.check("директоров двое: снять «Директор» у администратора можно (остаётся Дмитрий)", same(a2.platform_role_refs.map((y) => y.name), ["Администратор"]), JSON.stringify(a2.platform_role_refs.map((y) => y.name)));

  // --- последний директор
  await openCard(page, "Дмитрий Директоров");
  await panel.getByRole("checkbox", { name: /^Директор/ }).uncheck();
  await panel.getByRole("checkbox", { name: /^Менеджер(?! и)/ }).check();
  await panel.getByRole("button", { name: "Сохранить роли" }).click();
  await panel.getByRole("alert").first().waitFor({ timeout: 15000 });
  const t2 = await panel.getByRole("alert").first().innerText();
  r.check("снять «Директор» у единственного директора: «Нельзя снять роль директора или отключить последнего директора. Сначала назначьте директором другого сотрудника.»", /Нельзя снять роль директора/.test(t2) && /назначьте директором другого/.test(t2), t2);
  await screen(page, r, "last-director", { widths: [1440, 1280, 390], save: [1440, 390] });
  x = await bff(page, "PATCH", `/admin/users/${dirU.id}`, { role_ids: [String(role("Менеджер").id)] });
  r.check("BFF: снять DIRECTOR у последнего → 409 LAST_DIRECTOR", x.status === 409 && x.body?.code === "LAST_DIRECTOR", `${x.status} ${x.body?.code}`);
  x = await bff(page, "PATCH", `/admin/users/${dirU.id}`, { is_active: false });
  r.check("BFF: отключить последнего директора → 409 LAST_DIRECTOR", x.status === 409 && x.body?.code === "LAST_DIRECTOR", `${x.status} ${x.body?.code}`);
  x = await crm("PATCH", `/api/v1/users/${dirU.id}`, token, { platform_role_ids: [role("Менеджер").id] });
  r.check("CRM: снять DIRECTOR у последнего → 409 last_director", x.status === 409 && /last_director/i.test(JSON.stringify(x.body)), `${x.status} ${JSON.stringify(x.body).slice(0, 160)}`);
  // отключение через интерфейс
  await openCard(page, "Дмитрий Директоров");
  await panel.getByRole("button", { name: "Отключить сотрудника" }).click();
  await panel.getByRole("button", { name: "Отключить", exact: true }).click();
  await panel.getByRole("alert").first().waitFor({ timeout: 15000 });
  const t3 = await panel.getByRole("alert").first().innerText();
  r.check("отключить последнего директора в интерфейсе: понятный отказ", /директор/i.test(t3), t3);
  const d2 = await userByEmail(token, USERS.dir.email);
  r.check("директор по-прежнему активен и с ролью «Директор»", d2.is_active && d2.platform_role_refs.some((y) => y.code === "DIRECTOR"));
  // возврат: админ снова получает «Директор»
  x = await crm("PATCH", `/api/v1/users/${adminU.id}`, token, { platform_role_ids: [Number(ADM), Number(DIR)] });
  r.check("возврат: администратору снова выдан «Директор» (директоров двое)", x.status === 200, x.status);
  r.note("ошибки консоли", page.consoleErrors.join(" ;; ") || "нет");
  await ctx.close();
  r.save();
  return r;
};

// --- s10 (дополнительно): смена роли сотрудника на роль из шаблона; сотрудник видит новые разделы ------------------------
scenarios.s10 = async (browser) => {
  const r = new Report("s10");
  const c = C();
  const token = await adminToken();
  const mbt = await roleByName(token, MBT);
  const mb = await roleByName(token, MB);
  const mbU = await userByEmail(token, USERS.mb.email);
  const A = await newPage(browser);
  await loginOk(A.page, c.ADMIN_EMAIL, c.ADMIN_PW);
  const panel = A.page.locator(PANEL);
  await openCard(A.page, "Мария Бухгалтерова");
  await panel.getByRole("checkbox", { name: new RegExp(`^${esc(MB)}(?! \\()`) }).uncheck();
  await panel.getByRole("checkbox", { name: new RegExp(`^${esc(MBT)}`) }).check();
  const cons = (await panel.getByRole("group", { name: "Что произойдёт" }).innerText()).replace(/\n+/g, " | ");
  r.note("«Что произойдёт» при замене роли на роль из шаблона", cons);
  await screen(A.page, r, "swap-role-card", { widths: [1440], save: [1440] });
  await panel.getByRole("button", { name: "Сохранить роли" }).click();
  await A.page.getByText("Сохранено").first().waitFor();
  const mbRoleAccess = accessOf(await roleByName(token, MBT));
  const access = union([mbRoleAccess]);
  const erpRes = await pollUntil(async () => {
    const u = erpUser(USERS.mb.email);
    return sorted(erpAllPerms(u)).join() === sorted(erpPerms(access, [])).join() ? u : null;
  }, 120000, 4000);
  r.check("ERP: права «CRM Sync: mb» = права роли из шаблона (finance.*, deal.manage, data.export)", erpRes.ok, erpRes.ok ? `за ~${erpRes.sec} с: ${sorted(erpPerms(access, [])).join(",")}` : `факт: ${sorted(erpAllPerms(erpUser(USERS.mb.email))).join(",")}`);
  const permsMb = flattenPerms((await crm("GET", "/api/v1/me/permissions", await crmLogin(USERS.mb.email, c.PW_MB))).body.permissions);
  const miss = sorted(new Set([...crmPerms(access)].filter((p) => !permsMb.has(p))));
  r.check("CRM: права = каталог роли из шаблона (лиды full, клиенты full)", miss.length === 0, miss.join(",") || `${permsMb.size} прав`);
  // сотрудник входит заново и видит модули роли из шаблона
  const M = await newPage(browser);
  await loginOk(M.page, USERS.mb.email, c.PW_MB);
  const rail = await railTexts(M.page);
  r.check("сотрудник после входа: рейл = модули роли из шаблона (Dashboard, CRM, EDS, ERP, Chats)", same(rail, modulesFor(access)), rail.join(","));
  r.note("страница после входа и подпись под аватаром", `${new URL(M.page.url()).pathname}; ${await M.page.getByRole("button", { name: /профиль и настройки/i }).getAttribute("aria-label")}`);
  await screen(M.page, r, "mb-template-role-home", { widths: [1440, 390], save: [1440] });
  // поиск у роли с Dashboard: клиенты и лиды
  const search = M.page.getByRole("combobox", { name: "Глобальный поиск" });
  await search.click();
  await search.fill("Демо-Депо");
  await M.page.waitForTimeout(2500);
  const hits = await M.page.getByRole("option").allInnerTexts();
  r.note("поиск «Демо-Депо» у роли из шаблона", hits.map((h) => h.replace(/\n+/g, " / ")).join(" ;; ") || "ничего");
  await screen(M.page, r, "search-template-role", { widths: [1440], save: [1440] });
  // вернуть роль
  await M.ctx.close();
  const back = await crm("PATCH", `/api/v1/users/${mbU.id}`, token, { platform_role_ids: [mb.id] });
  r.check("возврат: сотруднику снова выдана «Менеджер и бухгалтер»", back.status === 200, back.status);
  await A.ctx.close();
  r.save();
  return r;
};

// --- s11 (дополнительно): поиск у роли без Dashboard («Менеджер и бухгалтер» = CRM + EDS) --------------------------------
scenarios.s11 = async (browser) => {
  const r = new Report("s11");
  const c = C();
  const { ctx, page } = await newPage(browser);
  await loginOk(page, USERS.mb.email, c.PW_MB);
  r.note("первая страница роли без Dashboard", new URL(page.url()).pathname);
  const search = page.getByRole("combobox", { name: "Глобальный поиск" });
  await search.click();
  await search.fill("Демо-Депо");
  await page.waitForTimeout(3000);
  const opts = (await page.getByRole("option").allInnerTexts()).map((h) => h.replace(/\n+/g, " / "));
  r.note("поиск «Демо-Депо» у «Менеджер и бухгалтер» (лиды — да, клиенты — нет)", opts.join(" ;; ") || "ничего не найдено");
  r.check("поиск у роли без Dashboard работает и находит лид, но не клиента", opts.some((o) => /Демо-Депо|Лидов/.test(o)) && !opts.some((o) => /ИНН 300000099|Клиент/.test(o)), opts.join(" ;; "));
  await screen(page, r, "search-no-dashboard", { widths: [1440, 1280, 390], save: [1440, 390] });
  await page.keyboard.press("Escape");
  // колокольчик и профиль на роли без Dashboard
  await page.getByRole("button", { name: /Центр уведомлений/ }).click();
  await page.waitForTimeout(800);
  await screen(page, r, "bell-no-dashboard", { widths: [1440, 390], save: [1440] });
  await ctx.close();
  r.save();
  return r;
};

// --- s12 (дополнительно): журнал CRM и «хотя бы одна роль» ------------------------------------------------------------
scenarios.s12 = async (browser) => {
  const r = new Report("s12");
  const c = C();
  const token = await adminToken();
  for (const action of ["platform_role.create", "platform_role.update", "platform_role.delete", "user.update"]) {
    const a = await crm("GET", `/api/v1/audit?action=${action}&limit=1`, token);
    const it = a.body.items?.[0];
    r.check(`журнал CRM: есть «${action}»`, !!it && it.actor_name, it ? `последняя: ${it.created_at}, ${it.actor_name}, сущность ${it.entity_type}#${it.entity_id}` : "нет");
    if (action === "user.update" && it) r.note("user.update: «до» и «после»", `${JSON.stringify(it.before).slice(0, 160)} → ${JSON.stringify(it.after).slice(0, 200)}`);
  }
  const { ctx, page } = await newPage(browser);
  await loginOk(page, c.ADMIN_EMAIL, c.ADMIN_PW);
  const panel = page.locator(PANEL);
  await openCard(page, "Мария Бухгалтерова");
  await panel.getByRole("checkbox", { name: new RegExp(`^${esc(MB)}(?! \\()`) }).uncheck();
  await page.waitForTimeout(300);
  const t = await panel.innerText();
  r.check("снять все роли у сотрудника: «Выберите хотя бы одну роль…», «Сохранить роли» неактивна", /Выберите хотя бы одну роль/.test(t) && (await panel.getByRole("button", { name: "Сохранить роли" }).isDisabled()), (t.match(/Выберите хотя бы одну роль[^.]*\.[^.]*\./) ?? [""])[0]);
  await screen(page, r, "need-one-role", { widths: [1440], save: [1440] });
  // сотрудник без активных лидов: PATCH с пустым набором ролей через BFF и CRM (интерфейс это запрещает)
  const mgr = (await platformRoles(token)).find((y) => y.name === "Менеджер");
  let tmp = await userByEmail(token, "tmp@demo.example");
  if (!tmp) {
    const created = await crm("POST", "/api/v1/users", token, { email: "tmp@demo.example", full_name: "Временный Тест", platform_role_ids: [mgr.id] });
    tmp = created.body.user;
  } else await crm("PATCH", `/api/v1/users/${tmp.id}`, token, { is_active: true, platform_role_ids: [mgr.id] });
  const x = await bff(page, "PATCH", `/admin/users/${tmp.id}`, { role_ids: [] });
  const tmpAfter = await userByEmail(token, "tmp@demo.example");
  r.check("BFF: PATCH role_ids=[] отклоняется (интерфейс говорит «хотя бы одну роль»)", x.status >= 400 && x.status < 500, `статус ${x.status}; в CRM после запроса: роли=${JSON.stringify(tmpAfter.platform_role_refs.map((y) => y.name))}, базовая=${JSON.stringify(tmpAfter.roles)}, доступ=${JSON.stringify(tmpAfter.platform_access)}, активен=${tmpAfter.is_active}`);
  await crm("PATCH", `/api/v1/users/${tmp.id}`, token, { is_active: false });
  await ctx.close();
  r.save();
  return r;
};

// --- s13 (дополнительно): активная роль универсала (Администратор + Директор) ----------------------------------------------
scenarios.s13 = async (browser) => {
  const r = new Report("s13");
  const c = C();
  const token = await adminToken();
  const roles = await platformRoles(token);
  const admin = roles.find((x) => x.code === "ADMIN");
  const dir = roles.find((x) => x.code === "DIRECTOR");
  const { ctx, page } = await newPage(browser);
  await loginOk(page, c.ADMIN_EMAIL, c.ADMIN_PW);
  const pick = async (name) => {
    await openAvatarMenu(page);
    await page.getByRole("menuitem", { name, exact: true }).click();
    await page.waitForTimeout(900);
  };
  for (const [name, rolesOf] of [["Администратор", [admin]], ["Директор", [dir]], ["Все роли", [admin, dir]]]) {
    await pick(name);
    const access = union(rolesOf.map(accessOf));
    const rail = await railTexts(page);
    r.check(`активная роль «${name}»: рейл = модули ${rolesOf.map((x) => `«${x.name}»`).join(" + ")}`, same(rail, modulesFor(access)), `факт=${rail.join(",")}; ожидание=${modulesFor(access).join(",")}`);
    const hidden = routesFor(access).hidden;
    if (hidden.length) r.check(`активная роль «${name}»: чужой раздел ${hidden[0]} → «Нет доступа»`, await forbidden(page, hidden[0]));
    else r.note(`активная роль «${name}»: закрытых разделов нет`);
    await spaGoto(page, "/dashboard/queue");
    if (name === "Администратор") await screen(page, r, "active-role-admin", { widths: [1440, 390], save: [1440] });
  }
  await pick("Администратор");
  await page.reload();
  await page.getByRole("heading", { level: 1 }).first().waitFor();
  r.note("активная роль «Администратор» после перезагрузки страницы — рейл", (await railTexts(page)).join(","));
  await pick("Все роли");
  await ctx.close();
  r.save();
  return r;
};

export async function main() {
  const names = process.argv.slice(2);
  const browser = await launch();
  let failed = 0;
  for (const n of names) {
    if (!scenarios[n]) throw new Error(`нет сценария ${n}`);
    console.log(`\n=== ${n} ===`);
    const r = await scenarios[n](browser);
    failed += r.rows.filter((x) => x.ok === false).length;
  }
  await browser.close();
  console.log(`\nНе пройдено проверок: ${failed}; сбоев входа (503 BFF, повтор): ${loginFlakes.length}${loginFlakes.length ? " — " + loginFlakes.join(" ;; ") : ""}`);
}
export { scenarios };
await main();
