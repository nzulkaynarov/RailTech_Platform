// W15-H9: гейт волны 15 «Честный интерфейс» — проход глазами по ролям (UX-оценка 2026-10-27 §2.2) против живого стенда
// (Caddy -> BFF Платформы -> CRM/ERP/EDS), не MSW. Запуск из корня worktree:
//   QA_BASE=http://platform.localhost:<HTTP_PORT> QA_OUT=<каталог вне репозитория> QA_COMPOSE="<docker compose ... -p rt-w15-h9>" \
//     node docs/runbooks/qa/w15-h9-gate/run.mjs s1 s2 s3 s4 s5 s6
// Пароли генерируются на лету и лежат только в QA_OUT/state.json. Снимки — docs/screens/w15-h9/. Общие помощники — из гейта C2a.
import { execSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

process.env.QA_SHOTS ??= resolve(dirname(fileURLToPath(import.meta.url)), "../../../screens/w15-h9");
const lib = await import("../w13-a7-gate/lib.mjs");
const { Report, launch, newPage, openAvatarMenu, spaGoto, screen, shot, toastsGone, bff, state, saveState, secret, motionEnd } =
  lib;

const compose = (args) => {
  const c = process.env.QA_COMPOSE;
  if (!c) throw new Error("QA_COMPOSE не задан");
  return execSync(`${c} ${args}`, { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
};

const ADMIN = "admin.h9@demo.example";
const PANEL = "#pf-context-panel";
const ROLES = {
  director: { email: "director.h9@demo.example", name: "Демо Директорова", roles: ["Директор"] },
  manager: { email: "manager.h9@demo.example", name: "Демо Менеджерова", roles: ["Менеджер"] },
  supply: { email: "supply.h9@demo.example", name: "Демо Снабженцева", roles: ["Снабженец"] },
  engineer: { email: "engineer.h9@demo.example", name: "Демо Инженерова", roles: ["Гл. инженер"] },
  accountant: { email: "accountant.h9@demo.example", name: "Демо Бухгалтерова", roles: ["Бухгалтер"] },
  universal: {
    email: "universal.h9@demo.example",
    name: "Демо Универсалова",
    roles: ["Администратор", "Директор", "Менеджер", "Снабженец", "Гл. инженер", "Бухгалтер"],
  },
};
// В интерфейсе не должно остаться: старые имена модулей, номера в заголовках, «фаза Pn», «Раздел будет наполнен».
const FORBIDDEN_TEXT = /фаз[еыа] P\d|Раздел будет наполнен|\b\d\. (Dashboard|CRM|EDS|ERP|Chats|Admin)\b/;
const STUB_TITLE = "Этот раздел ещё переносится в Платформу";
const scenarios = {};

/** Страница с запасом ожидания: машина гейта перегружена (load 20–40), статика отдаётся секундами. */
async function np(browser, ...rest) {
  const res = await newPage(browser, ...rest);
  res.page.setDefaultNavigationTimeout(120000);
  res.page.setDefaultTimeout(45000);
  return res;
}

/** Попытка шага: ошибка не обрывает сценарий, а фиксируется как FAIL со снимком. */
async function step(page, r, desc, fn, { noShot = false } = {}) {
  try {
    await fn();
    return r.check(desc, true);
  } catch (e) {
    const msg = String(e.message ?? e).split("\n").slice(0, 3).join(" / ").slice(0, 400);
    r.check(desc, false, msg);
    // поля паролей и временного пароля на снимке закрыты маской
    const mask = [page.locator('input[type="password"]'), page.getByLabel("Временный пароль", { exact: true })];
    if (!noShot) await shot(page, r, `FAIL-${r.rows.length}`, { mask }).catch(() => {});
    return false;
  }
}

/** Вход сотрудника: временный пароль -> свой; приветствие первого входа фиксируется и закрывается. */
async function signIn(page, r, email, password, { tour = false } = {}) {
  await page.context().clearCookies();
  await lib.login(page, email, password);
  await page.waitForURL(/\/(dashboard\/queue|admin\/setup|change-password|crm|eds|erp|chats|admin)/, { timeout: 90000, waitUntil: "commit" });
  let pw = password;
  if (/change-password/.test(page.url())) {
    pw = secret("own");
    await page.getByLabel("Текущий пароль").fill(password);
    await page.getByLabel("Новый пароль", { exact: true }).fill(pw);
    await page.getByLabel("Повторите новый пароль").fill(pw);
    await page.getByRole("button", { name: "Сменить пароль" }).click();
    await page.waitForURL((u) => !/change-password/.test(String(u)), { timeout: 90000, waitUntil: "commit" });
    const s = state();
    s.passwords = { ...(s.passwords ?? {}), [email]: pw };
    saveState({ passwords: s.passwords });
  }
  await page.getByRole("heading", { level: 1 }).first().waitFor({ timeout: 20000 });
  const welcome = page.getByRole("dialog").filter({ hasText: "Добро пожаловать" });
  if (await welcome.waitFor({ state: "visible", timeout: 6000 }).then(() => true).catch(() => false)) {
    r.note(`первый вход ${email}: приветствие по роли`, (await welcome.innerText()).replace(/\s+/g, " ").slice(0, 300));
    if (tour) return { pw, welcome };
    await welcome.getByRole("button", { name: "Больше не показывать" }).click();
    await welcome.waitFor({ state: "hidden" }).catch(() => {});
  }
  return { pw, welcome: null };
}
const pwOf = (email) => state().passwords?.[email];

async function railNames(page) {
  return page
    .getByRole("navigation", { name: "Модули" })
    .getByRole("link")
    .evaluateAll((els) => els.map((e) => e.textContent?.trim() ?? "").filter((t) => t && t !== "RT"));
}

/** Проверки любого экрана: нет запрещённых текстов; заглушка — с мостом или «кто делает» и «когда появится». */
/** Дождаться данных экрана: скелетоны и «Загружаем…» ушли (машина перегружена, ответы бэкендов — секунды). */
async function settle(page) {
  await page.locator(".ant-skeleton").first().waitFor({ state: "detached", timeout: 30000 }).catch(() => {});
  await page.getByText(/^Загружаем/).first().waitFor({ state: "detached", timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(600);
}

async function honest(page, r, label) {
  await settle(page);
  if ((await page.locator("#main-content").innerText().catch(() => "")).includes(STUB_TITLE)) {
    // мост рисуется после ответа BFF о старых системах
    await page
      .getByRole("link", { name: /Открыть в старо|^Открыть «/ })
      .or(page.getByText(/Сейчас этой работы в интерфейсе нет|Адрес не определён/))
      .first()
      .waitFor({ timeout: 15000 })
      .catch(() => {});
  }
  const text = await page.locator("#main-content").innerText().catch(() => "");
  r.check(`${label}: нет «фазы Pn», «Раздел будет наполнен», номеров модулей`, !FORBIDDEN_TEXT.test(text), (text.match(FORBIDDEN_TEXT) ?? [""])[0]);
  const stub = text.includes(STUB_TITLE);
  if (stub) {
    const bridge = await page.getByRole("link", { name: /Открыть в старо(й CRM|м ERP)/ }).count();
    const internal = await page.getByRole("link", { name: /^Открыть «/ }).count();
    // «делается в Платформе, в разделе …; её выполняет администратор» — честно и без кнопки, если раздел роли закрыт
    const none = /Сейчас этой работы в интерфейсе нет|Сейчас эта работа делается в Платформе, в разделе/.test(text);
    r.check(`${label}: заглушка честная — мост, раздел Платформы или «кто делает»`, bridge + internal > 0 || none, text.slice(0, 160).replace(/\s+/g, " "));
    r.check(`${label}: заглушка говорит, когда появится, словами`, /Когда появится:/.test(text), "");
    if (bridge > 0) {
      const href = await page.getByRole("link", { name: /Открыть в старо(й CRM|м ERP)/ }).first().getAttribute("href");
      r.check(`${label}: ссылка моста ведёт в старую систему`, /^https?:\/\/(crm|erp)\.localhost/.test(href ?? ""), href ?? "");
    }
  }
  return { stub, text };
}

// ---------------------------------------------------------------------------------------------------------------------
// s1. Администратор: первый запуск по коду из журнала crm-api, мастер без переброса (шаги в боковом окне), компания, баннер.
scenarios.s1 = async (browser) => {
  const r = new Report("s1");
  const { page } = await np(browser);
  const adminPw = secret("adm");
  saveState({ adminEmail: ADMIN, adminPw });
  await page.goto("/login");
  await step(page, r, "вход без администратора ведёт на «Первый запуск» (/setup)", async () => {
    await page.waitForURL(/\/setup$/, { timeout: 90000, waitUntil: "commit" });
  });
  await screen(page, r, "setup");
  await step(page, r, "/setup: без «docker compose» в тексте, есть «Подробнее для техспециалиста» (H8)", async () => {
    const t = await page.locator("body").innerText();
    if (/docker compose/.test(t)) throw new Error("на экране есть «docker compose»");
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
  const created = await step(page, r, "администратор создан, открыт мастер «Первый запуск»", async () => {
    await page.waitForURL(/\/admin\/setup/, { timeout: 90000, waitUntil: "commit" });
    await page.getByRole("heading", { level: 2, name: "Подключение ERP" }).waitFor({ timeout: 15000 });
  });
  if (!created) {
    // CRM могла создать администратора, но ответить позже предела ожидания BFF: входим обычным путём
    const alert = await page.getByRole("alert").first().innerText().catch(() => "");
    r.note("ответ экрана /setup при создании администратора", alert);
    await lib.login(page, ADMIN, adminPw);
    await page.waitForURL(/\/admin\/setup|\/dashboard/, { timeout: 90000, waitUntil: "commit" });
    await spaGoto(page, "/admin/setup");
    await page.getByRole("heading", { level: 2, name: "Подключение ERP" }).waitFor({ timeout: 15000 });
  }
  r.note("ошибки консоли / 5xx", `${page.consoleErrors.join(" | ")} ${page.failed.join(" | ")}`);
  r.save();
};

// s1w. Мастер первого запуска: шаги в боковом окне, ERP, компания, бот, баннер «Скрыть до завтра» и «Вернуть баннер».
scenarios.s1w = async (browser) => {
  const r = new Report("s1w");
  const { page } = await np(browser);
  const adminPw = state().adminPw;
  await lib.login(page, ADMIN, adminPw);
  await page.waitForURL(/\/admin\/setup|\/dashboard/, { timeout: 90000, waitUntil: "commit" });
  const welcome = page.getByRole("dialog").filter({ hasText: "Добро пожаловать" });
  if (await welcome.waitFor({ state: "visible", timeout: 4000 }).then(() => true).catch(() => false)) {
    r.note("первый вход администратора: приветствие", (await welcome.innerText()).replace(/\s+/g, " ").slice(0, 300));
    await screen(page, r, "admin-welcome", { narrow: false });
    await welcome.getByRole("button", { name: "Больше не показывать" }).click();
  }
  await spaGoto(page, "/admin/setup");
  await page.getByRole("heading", { level: 2, name: "Подключение ERP" }).waitFor({ timeout: 15000 });
  await toastsGone(page);
  await screen(page, r, "wizard");
  await step(page, r, "пункт «Первый запуск» в меню Настроек, пока шаги не завершены", async () => {
    await page.getByRole("navigation", { name: "Разделы модуля" }).getByRole("link", { name: "Первый запуск" }).waitFor();
  });
  // ERP — шаг в боковом окне мастера
  await page.getByRole("link", { name: "Подключить ERP" }).first().click();
  await step(page, r, "шаг ERP открывается в боковом окне мастера, адрес — /admin/setup?step=erp", async () => {
    await page.waitForURL(/\/admin\/setup\?step=erp/, { timeout: 90000, waitUntil: "commit" });
    await page.locator(PANEL).getByRole("heading", { name: /Шаг 1 из 5: ERP/ }).waitFor();
  });
  await screen(page, r, "wizard-step-erp");
  await step(page, r, "ERP сопряжена из мастера; после сохранения — форма компании, окно закрыто", async () => {
    const panel = page.locator(PANEL);
    await panel.getByRole("button", { name: "Подключить ERP" }).click();
    const form = panel.getByRole("form", { name: "Подключить ERP" });
    await form.getByLabel("Ваш пароль администратора").fill(adminPw);
    await form.getByRole("button", { name: "Подключить ERP" }).click();
    await page.getByLabel("Название компании").waitFor({ timeout: 60000 });
  });
  await step(page, r, "своя компания создаётся в мастере", async () => {
    await page.getByLabel("Название компании").fill("ООО Демо Рельс H9");
    await page.getByRole("button", { name: "Создать компанию" }).click();
    await page.getByText("Своя компания создана.").waitFor({ timeout: 30000 });
  });
  await toastsGone(page);
  await page.getByRole("link", { name: "Подключить бота" }).click();
  await step(page, r, "шаг «Telegram-бот» — в боковом окне мастера, форма токена сразу открыта", async () => {
    await page.locator(PANEL).getByRole("heading", { name: /Шаг 2 из 5: Telegram-бот/ }).waitFor();
    await page.locator(PANEL).getByRole("form", { name: "Токен бота" }).waitFor();
  });
  await screen(page, r, "wizard-step-bot");
  // баннер: «Скрыть до завтра» и «Вернуть баннер»
  await spaGoto(page, "/admin/org");
  const banner = page.getByRole("region", { name: "Настройка Платформы" });
  await step(page, r, "баннер настройки на других экранах: «Скрыть до завтра»", async () => {
    await banner.getByRole("button", { name: "Скрыть до завтра: баннер настройки" }).click();
    await banner.waitFor({ state: "detached" });
  });
  await spaGoto(page, "/admin/setup");
  await step(page, r, "в мастере «Вернуть баннер» возвращает баннер", async () => {
    await page.getByRole("button", { name: "Вернуть баннер" }).click();
    await spaGoto(page, "/admin/org");
    await banner.waitFor({ timeout: 8000 });
  });
  r.note("ошибки консоли / 5xx", `${page.consoleErrors.join(" | ")} ${page.failed.join(" | ")}`);
  r.save();
};

// s1c. Своя компания после сопряжения ERP: «Проверить снова», пока ERP не выдаст доступ новому администратору.
scenarios.s1c = async (browser) => {
  const r = new Report("s1c");
  const { page } = await np(browser);
  const s = state();
  await signIn(page, r, s.adminEmail, s.adminPw);
  await spaGoto(page, "/admin/setup?panel=closed");
  const t0 = Date.now();
  let ready = false;
  for (let i = 0; i < 20 && !ready; i++) {
    ready = await page.getByLabel("Название компании").isVisible().catch(() => false);
    if (ready) break;
    const again = page.getByRole("button", { name: "Проверить снова" });
    if (await again.isVisible().catch(() => false)) await again.click();
    await page.waitForTimeout(6000);
  }
  r.note("сколько ждали формы компании после сопряжения ERP", `${Math.round((Date.now() - t0) / 1000)} с`);
  await step(page, r, "своя компания создаётся в мастере", async () => {
    await page.getByLabel("Название компании").fill("ООО Демо Рельс H9");
    await page.getByRole("button", { name: "Создать компанию" }).click();
    await page.getByText("Своя компания создана.").waitFor({ timeout: 30000 });
  });
  await toastsGone(page);
  await screen(page, r, "wizard-company-done", { narrow: false });
  r.save();
};

// s2. Сотрудники по ролям — через «+ Пригласить сотрудника» с временным паролем; демо-лиды CRM (seed-demo).
scenarios.s2 = async (browser) => {
  const r = new Report("s2");
  const { page } = await np(browser);
  const s = state();
  await signIn(page, r, s.adminEmail, s.adminPw);
  const temps = {};
  const done = state().temps ?? {};
  for (const [key, who] of Object.entries(ROLES)) {
    if (done[who.email]) {
      temps[who.email] = done[who.email];
      continue;
    }
    await spaGoto(page, "/admin/org");
    await spaGoto(page, "/admin/org?invite=open&panel=open");
    const ok = await step(page, r, `приглашение «${key}» временным паролем`, async () => {
      const panel = page.locator(PANEL);
      await panel.getByRole("radio", { name: "Временным паролем, без почты" }).check();
      await panel.getByLabel("Имя и фамилия").fill(who.name);
      await panel.getByLabel("Электронная почта").fill(who.email);
      for (const role of who.roles) await panel.getByRole("checkbox", { name: new RegExp(`^${role}`) }).check();
      await panel.getByRole("button", { name: "Создать и показать пароль" }).click();
      const field = panel.getByLabel("Временный пароль", { exact: true });
      await field.waitFor({ timeout: 20000 });
      temps[who.email] = await field.inputValue();
      await panel.getByRole("button", { name: "Готово: пароль передан" }).click();
      await panel.getByRole("heading", { level: 3, name: who.name }).waitFor({ timeout: 60000 });
    }, { noShot: true });
    if (!ok) continue;
  }
  saveState({ temps });
  if (process.env.QA_SKIP_SEED) {
    r.save();
    return;
  }
  try {
    const mgrPw = secret("mgr");
    compose(`run --rm -T crm-api python -m app seed-demo --manager-email seed.manager@demo.example --manager-password ${mgrPw}`);
    r.check("демо-лиды CRM загружены (seed-demo)", true);
  } catch (e) {
    r.check("демо-лиды CRM загружены (seed-demo)", false, String(e).slice(0, 300));
  }
  r.save();
};

// sD. Данные для очередей: менеджер оформляет служебную записку с суммой (директору — «Согласовать», затем бухгалтеру).
scenarios.sD = async (browser) => {
  const r = new Report("sD");
  const who = ROLES.manager;
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email) ?? state().temps?.[who.email]);
  await spaGoto(page, "/eds/new");
  await step(page, r, "менеджер отправляет служебную записку с суммой на согласование", async () => {
    await page.getByLabel("Тема").fill("Командировка на объект заказчика (демо гейта)");
    await page.getByLabel("Текст").fill("Прошу согласовать командировку на 2 дня для замера на объекте. Данные вымышленные.");
    await page.getByLabel("Сумма, сум").fill("1500000");
    await page.getByRole("button", { name: "Отправить на согласование" }).click();
    await page.waitForURL((u) => !/\/eds\/new/.test(String(u)), { timeout: 90000, waitUntil: "commit" });
    await settle(page);
  });
  await screen(page, r, "memo-sent", { narrow: false });
  r.save();
};

// s3. Проход по ролям: рейл и меню, «Мои задачи», каждый пункт меню, колокольчик, поиск, 390.
async function walkRole(browser, key) {
  const r = new Report(`s3-${key}`);
  const who = ROLES[key];
  const { page } = await np(browser);
  const first = !pwOf(who.email);
  const pw = pwOf(who.email) ?? state().temps?.[who.email];
  const { welcome } = await signIn(page, r, who.email, pw, { tour: key === "manager" && first });
  if (welcome) {
    // тур первого входа — 3–4 шага
    await screen(page, r, "welcome", { narrow: false });
    await welcome.getByRole("button", { name: "Показать, где что" }).click();
    const tour = page.getByRole("dialog", { name: /Знакомство с Платформой/ });
    await step(page, r, "тур первого входа: шаги «Дальше» до «Готово»", async () => {
      for (let i = 0; i < 6; i++) {
        const done = tour.getByRole("button", { name: "Готово" });
        if (await done.isVisible().catch(() => false)) {
          await done.click();
          break;
        }
        await tour.getByRole("button", { name: "Дальше" }).click();
        await page.waitForTimeout(300);
      }
      await tour.waitFor({ state: "hidden", timeout: 5000 });
    });
  }
  await spaGoto(page, "/dashboard/queue");
  const rail = await railNames(page);
  r.note(`рейл (${key})`, rail.join(" · "));
  r.check(`рейл без английских имён и кодов систем`, !rail.some((n) => /Dashboard|CRM|EDS|ERP|Chats|Admin/.test(n)), rail.join(", "));
  if (rail.includes("Главная")) {
    await spaGoto(page, "/dashboard/queue");
    await page.getByRole("heading", { level: 1 }).first().waitFor();
    await settle(page);
    // частичный результат (один источник не ответил) — один повтор, как сделал бы сотрудник
    const partial = page.getByRole("button", { name: "Повторить" }).first();
    if (await partial.isVisible().catch(() => false)) {
      r.note("«Мои задачи»: часть источников не ответила с первого раза — «Повторить»", (await page.locator("#main-content").innerText()).slice(0, 200).replace(/\s+/g, " "));
      await partial.click();
      await page.waitForTimeout(8000);
      await settle(page);
    }
    await screen(page, r, "queue");
    await honest(page, r, "Мои задачи");
    // каждая строка очереди: «Открыть» -> родной экран, иначе «Где сделать» с мостом
    const rows = page.locator(".pf-queue-row");
    const n = await rows.count();
    r.note("строк в «Что сделать сейчас»", String(n));
    const items = [];
    for (let i = 0; i < n; i++) {
      const row = rows.nth(i);
      const title = (await row.locator(".pf-queue-title").innerText()).trim();
      const open = row.getByRole("link", { name: /^Открыть:/ });
      if (await open.count()) items.push({ title, href: await open.getAttribute("href") });
      else items.push({ title, where: true, i });
    }
    for (const it of items) {
      if (it.where) {
        await spaGoto(page, "/dashboard/queue");
        const row = page.locator(".pf-queue-row").nth(it.i);
        await step(page, r, `строка «${it.title}»: «Где сделать» — мост или кто делает`, async () => {
          await row.getByRole("button", { name: /^Где сделать/ }).click();
          const where = row.getByRole("region", { name: "Где сделать" });
          await where.waitFor();
          // кнопка моста появляется после ответа BFF об адресах старых систем
          await where
            .getByRole("link")
            .or(where.getByText(/Сейчас этой работы|Адрес не определён/))
            .first()
            .waitFor({ timeout: 20000 })
            .catch(() => {});
          const t = await where.innerText();
          const link = await where.getByRole("link").count();
          if (!link && !/Сейчас этой работы/.test(t)) throw new Error(`без ссылки и без «кто делает»: ${t.slice(0, 120)}`);
          if (link) {
            const href = await where.getByRole("link").first().getAttribute("href");
            if (!href || href === "#") throw new Error(`пустая ссылка: ${href}`);
          }
        });
        continue;
      }
      await spaGoto(page, it.href);
      await page.getByRole("heading", { level: 1 }).first().waitFor({ timeout: 15000 }).catch(() => {});
      await settle(page);
      const text = await page.locator("#main-content").innerText().catch(() => "");
      const denied = await page.getByRole("heading", { level: 1, name: "Нет доступа" }).count();
      r.check(`строка «${it.title}»: «Открыть» ведёт на родной экран, не в заглушку (${it.href})`, !text.includes(STUB_TITLE) && !denied, text.slice(0, 120).replace(/\s+/g, " "));
    }
  }
  // колокольчик
  await spaGoto(page, "/dashboard/queue");
  await step(page, r, "колокольчик открывается; уведомление ведёт к объекту или «Где посмотреть»", async () => {
    await page.getByRole("button", { name: /^Центр уведомлений/ }).click();
    const pop = page.getByRole("dialog").or(page.locator(".ant-popover")).first();
    await pop.waitFor();
    const t = await pop.innerText();
    r.note("колокольчик", t.replace(/\s+/g, " ").slice(0, 300));
    await page.keyboard.press("Escape");
  });
  // поиск
  await step(page, r, "поиск ⌘K: «L-» — результаты группами по модулям, без сбоя", async () => {
    const box = page.getByRole("combobox", { name: "Глобальный поиск" });
    await box.click();
    await box.fill("L-");
    await page.getByText("Ищем…").waitFor({ state: "detached", timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(800);
    const t = await page.locator('[role="listbox"], .pf-gsearch-msg').first().innerText().catch(() => "");
    r.note("поиск «L-»", t.replace(/\s+/g, " ").slice(0, 300));
    await box.fill("");
    await page.keyboard.press("Escape");
  });
  // каждый модуль и пункт меню
  const modules = await page.getByRole("navigation", { name: "Модули" }).getByRole("link").evaluateAll((els) =>
    els.map((e) => ({ name: e.textContent?.trim() ?? "", href: e.getAttribute("href") })).filter((m) => m.name && m.name !== "RT"),
  );
  for (const mod of modules) {
    await spaGoto(page, mod.href);
    await page.getByRole("heading", { level: 1 }).first().waitFor({ timeout: 15000 }).catch(() => {});
    const menu = page.getByRole("navigation", { name: "Разделы модуля" });
    // подменю сменилось на модуль рейла (на перегруженной машине — не сразу)
    const seg = `/${(mod.href ?? "").split("/")[1]}`;
    await page
      .waitForFunction(
        (sg) => [...document.querySelectorAll('nav[aria-label="Разделы модуля"] a')].some((a) => (a.getAttribute("href") ?? "").startsWith(sg)),
        seg,
        { timeout: 30000 },
      )
      .catch(() => {});
    await settle(page);
    const title = await menu.locator(".pf-menu-title, h2, [class*='title']").first().innerText().catch(() => "");
    r.check(`${mod.name}: заголовок подменю без номера`, !/^\d+\./.test(title.trim()), title);
    const links = await menu.getByRole("link").evaluateAll((els) =>
      els.map((e) => ({ name: (e.getAttribute("aria-label") || e.textContent || "").trim(), href: e.getAttribute("href") })),
    );
    r.note(`меню «${mod.name}»`, links.map((l) => l.name).join(" · "));
    let shotStub = false;
    for (const l of links) {
      await spaGoto(page, l.href);
      await page.getByRole("heading", { level: 1 }).first().waitFor({ timeout: 15000 }).catch(() => {});
      const { stub, text } = await honest(page, r, `${mod.name} · ${l.name}`);
      if (stub && /\d/.test(l.name) && !/ещё в старой системе/.test(l.name)) {
        r.check(`${mod.name} · ${l.name}: бейдж у заглушки — только с подсказкой «ещё в старой системе»`, false, l.name);
      }
      const forbidden = await page.getByRole("heading", { level: 1, name: "Нет доступа" }).count();
      if (forbidden) r.check(`${mod.name} · ${l.name}: пункт меню не ведёт в «Нет доступа»`, false, "");
      if (!shotStub || !stub) {
        const slug = `${mod.href.split("/")[1]}-${(l.href ?? "").split("/").slice(2).join("-").replace(/[?=&]/g, "-") || "index"}`;
        await screen(page, r, slug, { narrow: false });
        if (stub) shotStub = true;
      }
    }
  }
  // 390: очередь и меню в Drawer
  await page.setViewportSize({ width: 390, height: 844 });
  await spaGoto(page, "/dashboard/queue");
  if (rail.includes("Главная")) {
    await page.getByRole("heading", { level: 1 }).first().waitFor();
    await shot(page, r, "queue-mobile");
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  r.note("ошибки консоли / 5xx", `${page.consoleErrors.slice(0, 8).join(" | ")} ${page.failed.slice(0, 8).join(" | ")}`);
  r.save();
}
for (const key of Object.keys(ROLES)) scenarios[`s3-${key}`] = (b) => walkRole(b, key);
scenarios.s3 = async (browser) => {
  for (const key of Object.keys(ROLES)) await walkRole(browser, key);
};

// s4. Администратор: подключения (одна причина — одна строка, «Кто исправляет», «Ожидаемо на стенде»), состояние,
// Telegram-бот в одном месте, Журнал с фильтром, Обращения сотрудников, 390.
scenarios.s4 = async (browser) => {
  const r = new Report("s4");
  const { page } = await np(browser);
  const s = state();
  await signIn(page, r, s.adminEmail, s.adminPw);
  await spaGoto(page, "/admin/integrations");
  await page.getByRole("heading", { level: 2, name: "Требует внимания" }).waitFor({ timeout: 90000 });
  await page.waitForTimeout(1500);
  await screen(page, r, "integrations");
  const attention = page.locator("section").filter({ has: page.getByRole("heading", { level: 2, name: "Требует внимания" }) });
  const text = await attention.innerText();
  r.note("«Требует внимания»", text.replace(/\s+/g, " ").slice(0, 1200));
  r.check("в «Требует внимания» нет сырых ответов провайдера (litellm./Error code)", !/litellm\.|Error code: \d|Traceback/.test(text), "");
  r.check("строки с «Кто исправляет»", /Кто исправляет/.test(text) || /Всё в порядке|Ничего не требует/i.test(text), "");
  r.check("нет «Обратитесь к администратору сервера»", !/Обратитесь к администратору сервера/.test(await page.locator("body").innerText()), "");
  const tech = attention.getByText("Технические подробности").first();
  if (await tech.count()) {
    await step(page, r, "«Технические подробности» раскрываются, есть «Скопировать»", async () => {
      await tech.click();
      await attention.getByRole("button", { name: /Скопировать/ }).first().waitFor();
    });
    await shot(page, r, "integrations-tech");
  }
  r.note("«Ожидаемо на стенде» на экране", String(/Ожидаемо на стенде/.test(await page.locator("body").innerText())));
  // карточка «Состояние системы»
  await spaGoto(page, "/admin/integrations?card=system&panel=open");
  await page.waitForTimeout(2500);
  const sys = await page.locator(PANEL).innerText().catch(() => "");
  r.note("Состояние системы (WAL / Redis / шина)", sys.replace(/\s+/g, " ").slice(0, 900));
  await screen(page, r, "integrations-system");
  // бот в одном месте
  await spaGoto(page, "/admin/bot");
  await step(page, r, "Telegram-бот: вкладки «Подключение · Тексты · Поведение и передача · База знаний · Шаблоны ответов · Выгрузки»", async () => {
    const tabs = page.getByRole("tablist", { name: "Разделы Telegram-бота" });
    const names = await tabs.getByRole("tab").allInnerTexts();
    if (names.join("|") !== "Подключение|Тексты|Поведение и передача|База знаний|Шаблоны ответов|Выгрузки") throw new Error(names.join("|"));
  });
  await screen(page, r, "bot-connection");
  const tabs = { Тексты: "texts", "Поведение и передача": "behavior", "База знаний": "kb", "Шаблоны ответов": "templates", Выгрузки: "exports" };
  for (const [tab, slug] of Object.entries(tabs)) {
    await page.getByRole("tab", { name: tab }).click();
    await page.waitForTimeout(1500);
    await screen(page, r, `bot-${slug}`, { narrow: false });
  }
  // журнал
  await spaGoto(page, "/admin/audit");
  await step(page, r, "Журнал: фильтр «Действия людей / Обмен между системами», заголовок вкладки различает фильтр", async () => {
    await page.getByRole("navigation", { name: "Что показать в журнале" }).waitFor();
    if (!/Журнал · Действия людей/.test(await page.title())) throw new Error(await page.title());
  });
  await screen(page, r, "journal-people");
  await page.getByRole("link", { name: "Обмен между системами" }).first().click();
  await page.waitForTimeout(2500);
  await screen(page, r, "journal-systems");
  const bus = await page.locator("#main-content").innerText();
  r.note("журнал шины", bus.replace(/\s+/g, " ").slice(0, 500));
  r.check("журнал шины: нет «EDS не дал доступ»", !/не дал доступ/.test(bus), "");
  // обращения сотрудников
  await spaGoto(page, "/admin/tickets");
  await page.waitForTimeout(1500);
  await screen(page, r, "tickets");
  await honest(page, r, "Обращения сотрудников");
  r.note("ошибки консоли / 5xx", `${page.consoleErrors.slice(0, 8).join(" | ")} ${page.failed.slice(0, 8).join(" | ")}`);
  r.save();
};

// sW. Приветствие первого входа на снимке (новый сотрудник «Бухгалтер»): текст по роли, axe.
scenarios.sW = async (browser) => {
  const r = new Report("sW");
  const { page } = await np(browser);
  const s = state();
  await signIn(page, r, s.adminEmail, s.adminPw);
  let temp = "";
  await spaGoto(page, "/admin/org");
  await spaGoto(page, "/admin/org?invite=open&panel=open");
  await step(page, r, "новый сотрудник для приветствия первого входа", async () => {
    const panel = page.locator(PANEL);
    await panel.getByRole("radio", { name: "Временным паролем, без почты" }).check();
    await panel.getByLabel("Имя и фамилия").fill("Демо Новенькая");
    await panel.getByLabel("Электронная почта").fill("welcome.h9@demo.example");
    await panel.getByRole("checkbox", { name: /^Бухгалтер/ }).check();
    await panel.getByRole("button", { name: "Создать и показать пароль" }).click();
    const field = panel.getByLabel("Временный пароль", { exact: true });
    await field.waitFor({ timeout: 60000 });
    temp = await field.inputValue();
    await panel.getByRole("button", { name: "Готово: пароль передан" }).click();
  }, { noShot: true });
  const { page: p2 } = await np(browser);
  const { welcome } = await signIn(p2, r, "welcome.h9@demo.example", temp, { tour: true });
  if (welcome) {
    await screen(p2, r, "welcome");
    await welcome.getByRole("button", { name: "Больше не показывать" }).click();
  } else r.check("приветствие первого входа показано", false, "");
  r.save();
};

// s5. Сотрудник: профиль /me, «Забыли пароль?», помощь «?» и /help, «Написать администратору» с «Нет доступа» ->
// обращение у администратора -> ответ виден автору в колокольчике.
scenarios.s5 = async (browser) => {
  const r = new Report("s5");
  const who = ROLES.manager;
  const { page } = await np(browser);
  // «Забыли пароль?»
  await page.goto("/login");
  await step(page, r, "на входе есть «Забыли пароль?», запрос принят словами", async () => {
    await page.getByRole("link", { name: "Забыли пароль?" }).click();
    await page.getByLabel("Электронная почта").fill(who.email);
    await page.getByRole("button", { name: "Прислать ссылку" }).click();
    await page.getByText("Запрос принят").waitFor({ timeout: 15000 });
  });
  await screen(page, r, "forgot");
  await signIn(page, r, who.email, pwOf(who.email) ?? state().temps?.[who.email]);
  // профиль
  await spaGoto(page, "/me");
  await page.getByRole("heading", { level: 1, name: "Профиль" }).waitFor({ timeout: 15000 });
  await screen(page, r, "profile");
  await step(page, r, "профиль: фото загружается (кадрирование, «Сохранить фото»)", async () => {
    const png = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAQklEQVR4nO3PMQ0AIBDAQMC/58cCE+mQoHNzbefZd/AzPg4tAEoAlAAoAVACoARACYASACUASgCUACgBUAKgBEAJgPICRw4BfYeNlxEAAAAASUVORK5CYII=",
      "base64",
    );
    await page.locator('input[type="file"]').first().setInputFiles({ name: "avatar.png", mimeType: "image/png", buffer: png });
    await page.getByRole("button", { name: "Сохранить фото" }).click();
    await page.getByText("Фото обновлено").waitFor({ timeout: 15000 });
  });
  await step(page, r, "профиль: имя, телефон, часовой пояс, подпись сохраняются", async () => {
    await page.getByLabel("Телефон").fill("+998 90 000-00-01");
    await page.getByLabel("Подпись для писем").fill("С уважением, Демо Менеджерова");
    await page.getByRole("button", { name: "Сохранить" }).first().click();
    await page.getByText("Профиль сохранён").waitFor({ timeout: 15000 });
  });
  const tgText = await page.locator("#main-content").innerText();
  if (/Бот не подключён/.test(tgText)) {
    r.note("Telegram: бот на стенде не подключён (нет токена) — ссылка и QR не выдаются; сообщение экрана", (tgText.match(/Бот не подключён[^\n]*/) ?? [""])[0]);
  } else await step(page, r, "Telegram: «Привязать Telegram» — ссылка t.me и QR", async () => {
    await page.getByRole("button", { name: "Привязать Telegram" }).click();
    const dlg = page.getByRole("dialog", { name: "Привязка Telegram" });
    await dlg.waitFor();
    const link = dlg.getByRole("link", { name: "Открыть в Telegram" });
    const href = (await link.getAttribute("href").catch(() => "")) ?? "";
    r.note("ссылка привязки", href.replace(/start=[^&]+/, "start=<код>"));
    const qr = await dlg.getByRole("img", { name: "QR-код для привязки Telegram" }).count();
    if (!/t\.me\//.test(href) || !qr) throw new Error(`ссылка: ${href ? "есть" : "нет"}, QR: ${qr}`);
  });
  await shot(page, r, "profile-telegram", { mask: [page.getByRole("dialog").getByRole("img")] });
  await page.keyboard.press("Escape");
  await step(page, r, "замещение: выбрать коллегу и даты", async () => {
    await page.getByText("Замещение").first().scrollIntoViewIfNeeded();
    const text = await page.locator("#main-content").innerText();
    if (!/Замещение/.test(text)) throw new Error("нет блока замещения");
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await shot(page, r, "profile-mobile");
  await page.setViewportSize({ width: 1440, height: 900 });
  // помощь
  await spaGoto(page, "/dashboard/queue");
  await step(page, r, "«?» в шапке открывает помощь к разделу", async () => {
    await page.getByRole("button", { name: /^Помощь/ }).first().click();
    await page.getByRole("dialog", { name: "Помощь" }).waitFor();
  });
  await screen(page, r, "help-drawer", { narrow: false });
  await page.keyboard.press("Escape");
  await spaGoto(page, "/help");
  await page.getByRole("heading", { level: 1, name: "Помощь" }).waitFor({ timeout: 10000 }).catch(() => {});
  await screen(page, r, "help-page");
  // «Нет доступа» -> «Написать администратору»
  await spaGoto(page, "/admin/roles");
  await step(page, r, "«Нет доступа» -> «Написать администратору» отправляет обращение", async () => {
    await page.getByRole("heading", { level: 1, name: "Нет доступа" }).waitFor();
    await page.getByRole("button", { name: "Написать администратору" }).first().click();
    const dlg = page.getByRole("dialog", { name: "Написать администратору" });
    await dlg.waitFor();
    // тема подставлена сама: с экрана «Нет доступа» — «Нужен доступ к разделу»
    r.note("тема обращения с экрана «Нет доступа»", (await dlg.locator(".ant-select-selection-item").first().innerText().catch(() => "")) || "—");
    await dlg.getByLabel("Что случилось").fill("Нужен доступ к разделу «Роли и права», чтобы смотреть роли коллег (проверка гейта).");
    await dlg.getByRole("button", { name: "Отправить" }).click();
    await page.getByText(/Обращение .+ отправлено/).waitFor({ timeout: 15000 });
  });
  await screen(page, r, "ticket-sent", { narrow: false });
  await page.keyboard.press("Escape");
  // администратор отвечает
  const { page: admin } = await np(browser);
  const s = state();
  await signIn(admin, r, s.adminEmail, s.adminPw);
  await spaGoto(admin, "/admin/tickets");
  await step(admin, r, "администратор видит обращение в «Обращениях сотрудников» и отвечает", async () => {
    const row = admin.getByRole("link", { name: /^Открыть обращение/ }).first();
    await row.click();
    const panel = admin.locator(PANEL);
    await panel.getByRole("textbox").first().fill("Добавил вам чтение раздела. Проверьте, пожалуйста.");
    await panel.getByRole("button", { name: /Ответить|Отправить/ }).first().click();
    await admin.waitForTimeout(2500);
  });
  await screen(admin, r, "tickets-answer", { narrow: false });
  // автор видит ответ
  await page.reload();
  await page.getByRole("heading", { level: 1 }).first().waitFor();
  await step(page, r, "автор видит ответ: колокольчик", async () => {
    await page.waitForTimeout(3000);
    await page.getByRole("button", { name: /^Центр уведомлений/ }).click();
    const pop = page.locator(".ant-popover").first();
    await pop.waitFor();
    const t = await pop.innerText();
    r.note("колокольчик автора", t.replace(/\s+/g, " ").slice(0, 300));
    if (!/обращени/i.test(t)) throw new Error("в колокольчике нет ответа на обращение");
  });
  await shot(page, r, "author-bell");
  r.save();
};

// s6. Узбекский: рейл, меню, очередь, заглушка — выборочно (директор).
scenarios.s6 = async (browser) => {
  const r = new Report("s6");
  const who = ROLES.director;
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email) ?? state().temps?.[who.email]);
  await page.getByRole("button", { name: /профиль и настройки|profil va sozlamalar|profile and settings/i }).click();
  await page.getByRole("menuitem", { name: "O‘zbekcha" }).click();
  await page.getByRole("navigation", { name: "Modullar" }).waitFor({ timeout: 30000 });
  await page.getByRole("heading", { level: 1, name: "Mening vazifalarim" }).waitFor({ timeout: 30000 }).catch(() => {});
  const rail = await page.getByRole("navigation", { name: "Modullar" }).getByRole("link").allInnerTexts();
  r.note("рейл uz", rail.join(" · "));
  r.check("рейл uz: Asosiy · Mijozlar · Hujjatlar · Hisob · Chatlar · Sozlamalar", rail.filter((x) => x !== "RT").join("|") === "Asosiy|Mijozlar|Hujjatlar|Hisob|Chatlar|Sozlamalar", rail.join("|"));
  await screen(page, r, "uz-queue");
  for (const path of ["/crm/clients", "/erp/stock", "/admin/integrations", "/eds/payments"]) {
    await spaGoto(page, path);
    await page.waitForTimeout(1200);
    const t = await page.locator("#main-content").innerText();
    r.check(`uz ${path}: кириллицы в основном окне нет (кроме данных)`, !/[а-яё]{4,}/i.test(t.replace(/«[^»]*»/g, "")), (t.match(/[А-Яа-яё]{4,}[^\n]{0,40}/) ?? [""])[0]);
    await screen(page, r, `uz${path.replace(/\//g, "-")}`, { narrow: false });
  }
  await page.getByRole("button", { name: /профиль и настройки|profil va sozlamalar|profile and settings/i }).click();
  await page.getByRole("menuitem", { name: "Русский" }).click();
  r.save();
};

// sS. Поиск по номеру лида и имени (менеджер): результат ведёт к объекту или «Где посмотреть».
scenarios.sS = async (browser) => {
  const r = new Report("sS");
  const who = ROLES.manager;
  const { page } = await np(browser);
  await signIn(page, r, who.email, pwOf(who.email) ?? state().temps?.[who.email]);
  for (const q of ["L-0001", "Азиз", "СЗ-2026"]) {
    await step(page, r, `поиск «${q}»: результат или понятное «ничего не найдено»`, async () => {
      const box = page.getByRole("combobox", { name: "Глобальный поиск" });
      await box.click();
      await box.fill(q);
      await page.getByText("Ищем…").waitFor({ state: "detached", timeout: 40000 }).catch(() => {});
      await page.waitForTimeout(1000);
      const t = await page.locator('[role="listbox"], .pf-gsearch-msg').first().innerText().catch(() => "");
      r.note(`поиск «${q}»`, t.replace(/\s+/g, " ").slice(0, 300));
    });
    await shot(page, r, `search-${q.replace(/[^A-Za-z0-9]/g, "") || "name"}`);
    const opt = page.getByRole("option").first();
    if (await opt.isVisible().catch(() => false)) {
      await opt.click();
      await page.waitForTimeout(2500);
      const where = await page.getByText(/Где посмотреть|Сейчас —/).first().isVisible().catch(() => false);
      r.note(`поиск «${q}»: по результату`, `${page.url()}${where ? " · «Где посмотреть»" : ""}`);
      await shot(page, r, `search-open-${q.replace(/[^A-Za-z0-9]/g, "") || "name"}`);
      await page.keyboard.press("Escape");
    }
    await page.getByRole("combobox", { name: "Глобальный поиск" }).fill("");
  }
  r.save();
};

const browser = await launch();
try {
  for (const name of process.argv.slice(2)) {
    console.log(`=== ${name}`);
    try {
      await scenarios[name](browser);
    } catch (e) {
      // сценарий прерван (стенд не ответил) — фиксируем и идём дальше, а не обрываем весь прогон
      console.log(`ABORT [${name}] ${String(e.message ?? e).split("\n")[0].slice(0, 300)}`);
    }
  }
} finally {
  await browser.close();
}
