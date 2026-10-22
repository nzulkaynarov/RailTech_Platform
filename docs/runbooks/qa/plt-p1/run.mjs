// QA-P1: сценарии гейта фазы P1 против живого стенда (Caddy → BFF → CRM/ERP). Запуск:
//   QA_CREDS=<файл KEY=VALUE вне репозитория> node docs/runbooks/qa/plt-p1/run.mjs s1 s2 s3 ...
// Порт и адрес — QA_BASE (по умолчанию http://platform.localhost:18089). Список сценариев и ожидания — в отчёте
// docs/runbooks/plt_p1_gate_report.md. Скрипт не меняет код приложений; сценарии 6, 7, 10 меняют данные своего стенда.
import { execFileSync } from "node:child_process";
import {
  BASE, SHOTS, Report, creds, launch, newPage, login, loginOk, openAvatarMenu, signOut, railTexts, motionEnd, spaGoto, screen,
  modulesFor, routesFor,
} from "./lib.mjs";

const C = creds();
const USERS = {
  manager: { email: "manager@demo.example", pw: C.PW_manager, roles: ["MANAGER"] },
  director: { email: "director@demo.example", pw: C.PW_director, roles: ["DIRECTOR"] },
  supply: { email: "supply@demo.example", pw: C.PW_supply, roles: ["SUPPLY"] },
  multi: { email: "multi@demo.example", pw: C.PW_multi, roles: ["MANAGER", "ADMIN"] },
  admin: { email: C.ADMIN_EMAIL, pw: C.ADMIN_PW, roles: ["ADMIN"] },
};
const ROLE_RU = { MANAGER: "Менеджер", DIRECTOR: "Директор", SUPPLY: "Снабженец", ENGINEER: "Гл. инженер", ACCOUNTANT: "Бухгалтер", ADMIN: "Администратор" };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const compose = (...args) => {
  const w = process.env.QA_COMPOSE;
  if (!w) throw new Error("QA_COMPOSE не задан: путь к обёртке docker compose проекта rt-p1-qa");
  return execFileSync(w, args, { encoding: "utf8" });
};

const scenarios = {};

// 1. Вход тремя сотрудниками с разными ролями; рейл по матрице; смена активной роли.
scenarios.s1 = async (browser) => {
  const r = new Report("s1");
  for (const key of ["manager", "director", "supply", "multi", "admin"]) {
    const u = USERS[key];
    const { ctx, page } = await newPage(browser);
    await loginOk(page, u.email, u.pw);
    const rail = await railTexts(page);
    const expected = modulesFor(u.roles);
    r.check(`${key} (${u.roles.join("+")}): рейл = матрица`, same(rail, expected), `факт=${rail.join(",")}; ожидание=${expected.join(",")}`);
    const caption = await page.getByRole("button", { name: /профиль и настройки/i }).getAttribute("aria-label");
    r.note(`${key}: подпись под аватаром`, caption);
    await screen(page, r, `login-${key}`, { narrow: key === "manager" });
    if (key === "multi") {
      // смена активной роли
      await openAvatarMenu(page);
      await page.screenshot({ path: `${SHOTS}/s1-avatar-menu-multi-1440.png` });
      r.note("меню аватара multi", (await page.getByRole("menu").innerText()).replace(/\n+/g, " | "));
      await page.keyboard.press("Escape");
      for (const role of ["MANAGER", "ADMIN"]) {
        await openAvatarMenu(page);
        await page.getByRole("menuitem", { name: ROLE_RU[role], exact: true }).click();
        await page.waitForTimeout(500);
        const got = await railTexts(page);
        const exp = modulesFor([role]);
        r.check(`multi: активная роль ${role} — рейл = матрица роли`, same(got, exp), `факт=${got.join(",")}; ожидание=${exp.join(",")}`);
        await screen(page, r, `active-role-${role.toLowerCase()}`, { narrow: role === "ADMIN" });
        // меню подменю CRM для роли
        const hiddenRoutes = routesFor([role]).hidden;
        for (const route of hiddenRoutes.slice(0, 3)) {
          await spaGoto(page, route);
          await page.waitForTimeout(400);
          const forbidden = await page.getByRole("heading", { level: 1, name: "Нет доступа" }).count();
          r.check(`multi как ${role}: ${route} — Forbidden`, forbidden === 1, `h1 'Нет доступа'=${forbidden}`);
        }
        await spaGoto(page, "/dashboard/queue");
      }
      await openAvatarMenu(page);
      await page.getByRole("menuitem", { name: "Все роли" }).click();
      await page.waitForTimeout(500);
      const all = await railTexts(page);
      r.check("multi: «Все роли» возвращает объединение", same(all, modulesFor(["MANAGER", "ADMIN"])), all.join(","));
      // активная роль переживает перезагрузку?
      await openAvatarMenu(page);
      await page.getByRole("menuitem", { name: ROLE_RU.MANAGER, exact: true }).click();
      await page.reload();
      await page.getByRole("heading", { level: 1 }).waitFor();
      const afterReload = await railTexts(page);
      r.note("multi: активная роль «Менеджер» после перезагрузки — рейл", afterReload.join(","));
    }
    if (key === "supply") {
      await openAvatarMenu(page);
      r.check("supply (одна роль): выбора роли в меню аватара нет", (await page.getByText("Активная роль").count()) === 0);
      await page.keyboard.press("Escape");
    }
    r.note(`${key}: ошибки консоли`, page.consoleErrors.join(" ;; ") || "нет");
    await ctx.close();
  }
  r.save();
  return r;
};

// 2. Каркас: рейл, подменю, шапка, боковое окно; сворачивание панелей и восстановление после перезагрузки.
scenarios.s2 = async (browser) => {
  const r = new Report("s2");
  const { ctx, page } = await newPage(browser);
  await loginOk(page, USERS.director.email, USERS.director.pw);
  const menu = page.getByRole("navigation", { name: "Разделы модуля" });
  const panel = page.getByRole("complementary", { name: "Боковое окно" });
  r.check("обе панели открыты по умолчанию", (await menu.isVisible()) && (await panel.isVisible()));
  await screen(page, r, "queue-default", { narrow: true });
  r.note("вкладки бокового окна", (await panel.getByRole("tab").allInnerTexts()).join(" | "));

  // подменю каждого модуля у директора (SPEC-v3 §6.2 дословно)
  const spec = {
    "/dashboard/queue": ["Моя очередь", "Все проекты", "Сводка по компании"],
    "/crm/leads": ["Все сообщения", "Все лиды", "Все клиенты", "Все заявки", "Каналы связи", "База знаний"],
    "/eds/documents": ["Все документы", "Входящие", "Исходящие", "Все проекты", "Черновик", "На согласовании", "Счета и оплаты"],
    "/erp/requests": ["Все запросы", "Расчёт", "Склад", "Справочники", "Документация"],
    "/chats": ["Все чаты", "Внутренний", "Внешний", "Контакты"],
    "/admin/org": ["Ролевая матрица (RBAC)", "Оргструктура", "Внешние интеграции", "Тикеты от команды"],
  };
  for (const [route, items] of Object.entries(spec)) {
    await page.goto(route);
    await page.getByRole("heading", { level: 1 }).waitFor();
    // подменю может быть свёрнуто по умолчанию (ERP · Расчёт) — открываем
    if ((await menu.count()) === 0) await page.getByRole("button", { name: "Меню" }).click().catch(() => {});
    const links = (await menu.getByRole("link").allInnerTexts()).map((s) => s.replace(/\s+\d+.*$/s, "").trim());
    const action = await menu.getByRole("button").allInnerTexts().catch(() => []);
    r.check(`подменю ${route}: пункты по SPEC-v3 §6.2`, same(links.filter((t) => items.includes(t)), items) , `факт=${links.join(" | ")}; кнопки=${action.join("/")}`);
    r.note(`подменю ${route}: заголовок и главное действие`, await menu.locator("..").innerText().then((t) => t.replace(/\n+/g, " | ").slice(0, 300)));
    await screen(page, r, `module-${route.split("/")[1]}`, { widths: [1440, 1280] });
  }

  // сворачивание
  await page.goto("/dashboard/queue");
  await page.getByRole("heading", { level: 1 }).waitFor();
  await page.getByRole("button", { name: "Свернуть меню" }).click();
  r.check("подменю свернулось", (await menu.count()) === 0);
  r.check("в шапке появилась кнопка «Меню»", (await page.getByRole("button", { name: "Меню" }).count()) === 1);
  await page.getByRole("button", { name: "Скрыть панель" }).click();
  r.check("боковое окно скрыто, ?panel=closed", (await panel.count()) === 0 && /panel=closed/.test(page.url()), page.url());
  await screen(page, r, "panels-collapsed", { narrow: true });
  await page.reload();
  await page.getByRole("heading", { level: 1 }).waitFor();
  r.check("после перезагрузки (?panel=closed) обе панели свёрнуты", (await menu.count()) === 0 && (await panel.count()) === 0);
  await page.goto("/dashboard/queue");
  await page.getByRole("heading", { level: 1 }).waitFor();
  r.check("тот же раздел без параметров — состояние восстановлено из localStorage", (await menu.count()) === 0 && (await panel.count()) === 0, page.url());
  // другой пользователь в том же браузере — свои умолчания
  await signOut(page);
  await loginOk(page, USERS.manager.email, USERS.manager.pw);
  r.check("другой сотрудник в том же браузере — панели по умолчанию (состояние по пользователю)", (await menu.isVisible()) && (await panel.isVisible()));
  await signOut(page);
  await loginOk(page, USERS.director.email, USERS.director.pw);
  r.check("директор после повторного входа — панели по-прежнему свёрнуты", (await menu.count()) === 0 && (await panel.count()) === 0);
  await page.getByRole("button", { name: "Меню" }).click();
  await page.getByRole("button", { name: "Панель", exact: true }).click();
  r.check("«Меню» и «Панель» возвращают панели", (await menu.isVisible()) && (await panel.isVisible()));
  await page.reload();
  await page.getByRole("heading", { level: 1 }).waitFor();
  r.check("после перезагрузки панели открыты", (await menu.isVisible()) && (await panel.isVisible()));
  // умолчания по приложению А
  await page.goto("/crm/leads");
  await page.getByRole("heading", { level: 1 }).waitFor();
  r.check("CRM · Все лиды: боковое окно скрыто по умолчанию (прил. А)", (await panel.count()) === 0);
  await page.goto("/erp/calc");
  await page.getByRole("heading", { level: 1 }).waitFor();
  r.check("ERP · Расчёт: подменю свёрнуто, боковое открыто (прил. А)", (await menu.count()) === 0 && (await panel.isVisible()));
  await screen(page, r, "erp-calc-defaults", { widths: [1440, 1280] });
  // 390: нижняя панель, Drawer подменю
  await page.goto("/dashboard/queue");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(500);
  const bottom = await page.getByRole("navigation", { name: "Модули" }).boundingBox();
  r.check("390: рейл модулей — нижняя панель", !!bottom && bottom.y > 600, JSON.stringify(bottom));
  await page.getByRole("button", { name: "Меню" }).first().click().catch(() => {});
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${SHOTS}/s2-mobile-menu-drawer-390.png` });
  r.note("ошибки консоли", page.consoleErrors.join(" ;; ") || "нет");
  await ctx.close();
  r.save();
  return r;
};

// 3. Forbidden: прямой URL чужого раздела.
scenarios.s3 = async (browser) => {
  const r = new Report("s3");
  const cases = [
    ["manager", ["/admin/roles", "/dashboard/summary", "/erp/calc", "/admin/org"]],
    ["supply", ["/crm/leads", "/eds/inbox", "/admin/roles", "/eds/payments"]],
  ];
  for (const [key, routes] of cases) {
    const { ctx, page } = await newPage(browser);
    await loginOk(page, USERS[key].email, USERS[key].pw);
    for (const route of routes) {
      await page.goto(route);
      await page.getByRole("heading", { level: 1 }).waitFor();
      await motionEnd(page);
      const h1 = await page.getByRole("heading", { level: 1 }).innerText();
      const ok = h1 === "Нет доступа";
      r.check(`${key}: прямой URL ${route} → экран «Нет доступа»`, ok, `h1=${h1}`);
      const btn = page.getByRole("button", { name: /Написать администратору/ });
      r.check(`${key}: ${route}: кнопка «Написать администратору» есть и неактивна (Q-PLT-12-4)`, (await btn.count()) === 1 && (await btn.isDisabled()));
      r.check(`${key}: ${route}: боковое окно не показывается на Forbidden`, (await page.getByRole("complementary", { name: "Боковое окно" }).count()) === 0);
      if (route === routes[0]) {
        r.note(`${key}: текст экрана ${route}`, (await page.getByRole("main").innerText()).replace(/\n+/g, " | "));
        await screen(page, r, `forbidden-${key}`, { narrow: key === "manager" });
      }
    }
    // защита на уровне API: тот же запрет в BFF, не только в SPA
    const adminApi = await page.request.get("/api/v1/admin/users");
    r.check(`${key}: GET /api/v1/admin/users → 403 (BFF, не только SPA)`, adminApi.status() === 403, `status=${adminApi.status()} ${(await adminApi.text()).slice(0, 160)}`);
    if (key === "supply") {
      const sum = await page.request.get("/api/v1/queue/cards");
      r.note("supply: /queue/cards", `${sum.status()}`);
    }
    r.note(`${key}: ошибки консоли`, page.consoleErrors.join(" ;; ") || "нет");
    await ctx.close();
  }
  // чужая роль у сотрудника с несколькими ролями: активная роль «Бухгалтер» скрывает Admin, а «Все роли» — нет
  r.save();
  return r;
};

// 4. Уведомление из ERP видно в колоколе директора, открывает объект и вкладку бокового окна; «Отметить все прочитанными».
scenarios.s4 = async (browser) => {
  const r = new Report("s4");
  const { ctx, page } = await newPage(browser);
  await loginOk(page, USERS.director.email, USERS.director.pw);
  const bell = page.getByRole("button", { name: /^Центр уведомлений/ });
  await page.waitForFunction(() => /новых/.test(document.querySelector('button[aria-label^="Центр уведомлений"]')?.getAttribute("aria-label") ?? ""), null, { timeout: 10000 }).catch(() => {});
  const label = await bell.getAttribute("aria-label");
  r.check("колокольчик показывает число непрочитанных (4 заведены в ERP)", /4 новых/.test(label ?? ""), `aria-label=${label}`);
  await bell.click();
  const center = page.getByRole("dialog", { name: "Центр уведомлений" });
  await center.waitFor();
  r.note("вкладки центра", (await center.getByRole("tab").allInnerTexts()).join(" | "));
  r.note("записи центра", (await center.getByRole("link").allInnerTexts()).map((t) => t.replace(/\n+/g, " / ")).join(" || "));
  await screen(page, r, "bell-open", { narrow: true });
  // вкладка «Решения»
  await center.getByRole("tab", { name: /^Решения/ }).click();
  const decisions = await center.getByRole("listitem").count();
  r.check("вкладка «Решения»: 3 уведомления (КП на согласовании, заявка назначена, договор подписан)", decisions === 3, `listitem=${decisions}`);
  await center.getByRole("tab", { name: /^Система/ }).click();
  r.check("вкладка «Система»: 1 уведомление", (await center.getByRole("listitem").count()) === 1);
  await center.getByRole("tab", { name: /^Все/ }).click();
  // клик по уведомлению о КП
  await center.getByRole("link", { name: /КП на согласовании: Поставка крепежа/ }).click();
  await page.waitForTimeout(800);
  const url = decodeURIComponent(page.url());
  r.check("клик открывает объект: заявка ЗВ-2026-001 с ?panel=open&tab=documents", /\/crm\/requests\?request=ЗВ-2026-001&panel=open&tab=documents/.test(url), url);
  const panel = page.getByRole("complementary", { name: "Боковое окно" });
  r.check("боковое окно открыто", await panel.isVisible());
  const tabs = await panel.getByRole("tab").allInnerTexts();
  const selected = await panel.getByRole("tab", { selected: true }).allInnerTexts();
  r.note("вкладки бокового окна на объекте / выбрана", `${tabs.join(" | ")} / ${selected.join(",")}`);
  r.check("выбрана вкладка «Документы»", selected.includes("Документы"), selected.join(","));
  r.note("заголовок страницы и текст бокового окна", `${await page.getByRole("heading", { level: 1 }).innerText()} :: ${(await panel.innerText()).replace(/\n+/g, " | ").slice(0, 300)}`);
  await screen(page, r, "object-opened", { narrow: true });
  const label2 = await page.getByRole("button", { name: /^Центр уведомлений/ }).getAttribute("aria-label");
  r.check("счётчик уменьшился до 3", /3 новых/.test(label2 ?? ""), `aria-label=${label2}`);
  // «Отметить все прочитанными»
  await page.getByRole("button", { name: /^Центр уведомлений/ }).click();
  await center.waitFor();
  await center.getByRole("button", { name: "Отметить все прочитанными" }).click();
  await page.waitForTimeout(800);
  const label3 = await page.getByRole("button", { name: /^Центр уведомлений/ }).getAttribute("aria-label");
  r.check("после «Отметить все прочитанными» бейдж пропал", !/новых/.test(label3 ?? ""), `aria-label=${label3}`);
  r.check("в центре нет подсвеченных «Новое:»", (await center.getByText(/Новое:/).count()) === 0);
  await screen(page, r, "bell-all-read", { widths: [1440, 1280] });
  await page.keyboard.press("Escape");
  await page.reload();
  await page.getByRole("heading", { level: 1 }).waitFor();
  const label4 = await page.getByRole("button", { name: /^Центр уведомлений/ }).getAttribute("aria-label");
  r.check("после перезагрузки уведомления остались прочитанными (запись в ERP)", !/новых/.test(label4 ?? ""), `aria-label=${label4}`);
  // в ERP
  let erp = "";
  try {
    erp = compose("exec", "-T", "erp-backend", "python", "manage.py", "shell", "-c",
      "from core.models import Notification as N; print(N.objects.filter(user__email='director@demo.example', is_read=False).count(), N.objects.filter(user__email='director@demo.example').count())").trim().split("\n").pop();
  } catch (e) {
    erp = String(e).slice(0, 100);
  }
  r.check("в БД ERP непрочитанных у директора 0 из 4", /^0 4$/.test(erp), erp);
  // вкладка «Уведомления» бокового окна
  await page.goto("/dashboard/queue?panel=open&tab=notifications");
  await page.getByRole("heading", { level: 1 }).waitFor();
  r.check("вкладка «Уведомления» бокового окна выбрана по ?tab=notifications", (await page.getByRole("tab", { name: "Уведомления", selected: true }).count()) === 1);
  r.note("записи вкладки", (await page.getByRole("complementary", { name: "Боковое окно" }).getByRole("link").allInnerTexts()).map((t) => t.replace(/\n+/g, " / ")).join(" || "));
  await screen(page, r, "panel-notifications-tab", { narrow: true });
  // Лента «Сегодня»: админ видит запись журнала — проверка текста
  r.note("ошибки консоли", page.consoleErrors.join(" ;; ") || "нет");
  await ctx.close();
  r.save();
  return r;
};

// 5. Поиск ⌘K по номеру сделки.
scenarios.s5 = async (browser) => {
  const r = new Report("s5");
  const { ctx, page } = await newPage(browser);
  await loginOk(page, USERS.manager.email, USERS.manager.pw);
  const search = page.getByRole("combobox", { name: "Глобальный поиск" });
  await page.keyboard.press("Control+k");
  r.check("Ctrl+K фокусирует поиск", await search.evaluate((el) => el === document.activeElement));
  await page.keyboard.press("Escape");
  await page.locator("body").click({ position: { x: 700, y: 500 } });
  await page.keyboard.press("Meta+k");
  r.check("⌘K (Meta+K) фокусирует поиск", await search.evaluate((el) => el === document.activeElement));
  await search.fill("ЗВ-2026-001");
  const option = page.getByRole("option", { name: /ЗВ-2026-001 · Поставка крепежа/ });
  await option.waitFor({ timeout: 8000 }).catch(() => {});
  r.check("результат: «ЗВ-2026-001 · Поставка крепежа…»", (await option.count()) === 1, (await page.getByRole("listbox").innerText().catch(() => "—")).replace(/\n+/g, " | "));
  r.check("результаты сгруппированы по модулям (группа CRM)", (await page.getByRole("group", { name: "CRM" }).count()) >= 1);
  await screen(page, r, "search-results", { narrow: true });
  await search.press("ArrowDown");
  await search.press("Enter");
  await page.waitForTimeout(800);
  const url = decodeURIComponent(page.url());
  r.check("Enter открывает заявку: /crm/requests?request=ЗВ-2026-001&panel=open&tab=card", /\/crm\/requests\?request=ЗВ-2026-001&panel=open&tab=card/.test(url), url);
  r.note("страница после перехода", (await page.getByRole("heading", { level: 1 }).innerText()) + " :: " + (await page.getByRole("main").innerText()).replace(/\n+/g, " | ").slice(0, 250));
  await screen(page, r, "search-opened", { widths: [1440, 1280] });
  // другие запросы
  const variants = [["по названию «крепежа»", "крепежа", "ЗВ-2026-001"], ["по названию компании «Тестовая»", "Тестовая", "ЗВ-2026-002"], ["по части номера «2026-002»", "2026-002", "ЗВ-2026-002"], ["номер без нулей «ЗВ-2026-1»", "ЗВ-2026-1", "ЗВ-2026-001"], ["латиница в префиксе «ZV-2026-001»", "ZV-2026-001", "ЗВ-2026-001"]];
  for (const [title, q, expect] of variants) {
    await search.fill("");
    await search.fill(q);
    await page.waitForTimeout(1200);
    const txt = (await page.getByRole("listbox").innerText().catch(() => "")).replace(/\n+/g, " | ");
    const hit = txt.includes(expect);
    if (title.startsWith("номер без нулей") || title.startsWith("латиница")) r.note(`поиск ${title}`, hit ? `найдено: ${txt}` : `не найдено (${txt.slice(0, 120)})`);
    else r.check(`поиск ${title} находит ${expect}`, hit, txt.slice(0, 200));
  }
  await search.fill("нет-такого-номера");
  await page.waitForTimeout(1200);
  r.check("пустой результат — текст «ничего не найдено»", (await page.getByText(/ничего не найдено/).count()) >= 1);
  await screen(page, r, "search-empty", { widths: [1440, 1280] });
  // кнопка поиска на 390
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(400);
  await search.fill("");
  await search.fill("ЗВ-2026-002");
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SHOTS}/s5-search-390.png` });
  r.note("ошибки консоли", page.consoleErrors.join(" ;; ") || "нет");
  await ctx.close();
  // директор тоже находит; ограничение: у супплайера CRM-клиенты read, а сделки?
  const d = await newPage(browser);
  await loginOk(d.page, USERS.director.email, USERS.director.pw);
  const s = d.page.getByRole("combobox", { name: "Глобальный поиск" });
  await s.fill("ЗВ-2026-002");
  await d.page.waitForTimeout(1500);
  r.check("директор находит ЗВ-2026-002", (await d.page.getByRole("option", { name: /ЗВ-2026-002/ }).count()) === 1);
  await d.ctx.close();
  r.save();
  return r;
};

// 7. Обязательная смена пароля при первом входе приглашённого (must_change_password).
scenarios.s7 = async (browser) => {
  const r = new Report("s7");
  const { ctx, page } = await newPage(browser);
  const email = "newbie@demo.example";
  await login(page, email, C.TMP_newbie);
  await page.waitForURL(/\/change-password$/, { timeout: 15000 }).catch(() => {});
  r.check("вход с временным паролем ведёт на /change-password", /\/change-password$/.test(page.url()), page.url());
  await page.getByLabel("Текущий пароль").waitFor();
  r.note("текст экрана смены пароля", (await page.locator("main, body").first().innerText()).replace(/\n+/g, " | ").slice(0, 400));
  await screen(page, r, "change-password", { narrow: true });
  for (const route of ["/crm/leads", "/dashboard/queue", "/admin/org"]) {
    await page.goto(route);
    await page.waitForTimeout(700);
    r.check(`до смены пароля ${route} → снова /change-password`, /\/change-password$/.test(page.url()), page.url());
  }
  r.check("кнопки «Отмена» на обязательной смене нет", (await page.getByRole("button", { name: "Отмена" }).count()) === 0);
  // серверная сторона: данные до смены пароля через BFF
  const probes = {};
  for (const ep of ["/api/v1/me", "/api/v1/queue", "/api/v1/notifications", "/api/v1/search?q=2026"]) probes[ep] = (await page.request.get(ep)).status();
  r.note("BFF до смены пароля: статусы GET", JSON.stringify(probes));
  // валидация формы
  await page.getByLabel("Текущий пароль").fill("x");
  await page.getByLabel("Новый пароль", { exact: true }).fill("short");
  await page.getByLabel("Повторите новый пароль").fill("other");
  await page.getByRole("button", { name: "Сменить пароль" }).click();
  r.check("короткий пароль отклоняется на форме", (await page.getByText("Пароль должен быть не короче 8 символов").count()) === 1);
  r.check("несовпадение отклоняется на форме", (await page.getByText("Пароли не совпадают").count()) === 1);
  // неверный текущий
  const NEW = "Nn7-" + Math.random().toString(16).slice(2, 12);
  await page.getByLabel("Текущий пароль").fill("wrong-current-pw");
  await page.getByLabel("Новый пароль", { exact: true }).fill(NEW);
  await page.getByLabel("Повторите новый пароль").fill(NEW);
  await page.getByRole("button", { name: "Сменить пароль" }).click();
  await page.getByRole("alert").waitFor();
  const alertText = await page.getByRole("alert").innerText();
  r.check("неверный текущий пароль — понятный текст", /неверн/i.test(alertText), alertText);
  await screen(page, r, "change-password-error", { widths: [1440, 1280] });
  // успех
  await page.getByLabel("Текущий пароль").fill(C.TMP_newbie);
  await page.getByRole("button", { name: "Сменить пароль" }).click();
  await page.waitForURL(/\/dashboard\/queue/, { timeout: 15000 }).catch(() => {});
  r.check("после смены пароля — /dashboard/queue", /\/dashboard\/queue/.test(page.url()), page.url());
  const me = await (await page.request.get("/api/v1/me")).json();
  r.check("/me после смены: roles=[ACCOUNTANT]", JSON.stringify(me.roles ?? me.me?.roles) === '["ACCOUNTANT"]', JSON.stringify(me).slice(0, 200));
  await screen(page, r, "after-password-change", { widths: [1440, 1280] });
  const fs = await import("node:fs");
  fs.writeFileSync(`${process.env.QA_OUT}/pw_newbie.txt`, NEW);
  await ctx.close();
  // старый временный пароль больше не принимается
  const o = await newPage(browser);
  await login(o.page, email, C.TMP_newbie);
  await o.page.getByRole("alert").waitFor({ timeout: 8000 }).catch(() => {});
  r.check("временный пароль после смены не принимается", /\/login/.test(o.page.url()) && (await o.page.getByRole("alert").count()) === 1, o.page.url() + " " + (await o.page.getByRole("alert").allInnerTexts()).join("|"));
  await o.ctx.close();
  r.note("ошибки консоли", page.consoleErrors.join(" ;; ") || "нет");
  r.save();
  return r;
};

// 6. Admin · Оргструктура: выдача роли, повторный вход, директор — чтение, последний ADMIN, приглашение.
scenarios.s6 = async (browser) => {
  const r = new Report("s6");
  const PANEL = "#pf-context-panel";
  const fs = await import("node:fs");
  const newbiePw = fs.readFileSync(`${process.env.QA_OUT}/pw_newbie.txt`, "utf8").trim();
  // сессия новичка, открытая ДО выдачи роли
  const nb = await newPage(browser);
  await loginOk(nb.page, "newbie@demo.example", newbiePw);
  const before = await railTexts(nb.page);
  r.check("новичок (Бухгалтер) до выдачи роли: без Admin", !before.includes("Admin"), before.join(","));

  const { ctx, page } = await newPage(browser);
  await loginOk(page, USERS.admin.email, USERS.admin.pw);
  await spaGoto(page, "/admin/org");
  await page.getByRole("heading", { level: 1, name: "Оргструктура" }).waitFor();
  await page.getByRole("link", { name: /Открыть карточку: Новичок Демо/ }).waitFor();
  await screen(page, r, "org-list", { narrow: true });
  await page.getByRole("link", { name: /Открыть карточку: Новичок Демо/ }).click();
  const panel = page.locator(PANEL);
  await panel.getByRole("heading", { level: 3, name: "Новичок Демо" }).waitFor();
  r.check("карточка: чекбокс «Бухгалтер» отмечен, остальные нет", (await panel.getByRole("checkbox", { name: /^Бухгалтер/ }).isChecked()) && !(await panel.getByRole("checkbox", { name: /^Директор/ }).isChecked()));
  await panel.getByRole("checkbox", { name: /^Директор/ }).check();
  const willText = (await panel.getByRole("group", { name: "Что произойдёт" }).innerText().catch(() => "")).replace(/\n+/g, " ");
  r.check("«Что произойдёт»: модули по матрице и роли ERP (Руководитель + Финансы)", /Сотрудник увидит модули: Dashboard, CRM, EDS, ERP, Chats, Admin/.test(willText), willText);
  r.note("блок «Что произойдёт» целиком", willText);
  // высокий кадр
  for (const w of [1440, 1280]) {
    await page.setViewportSize({ width: w, height: 1300 });
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${SHOTS}/s6-org-card-roles-${w}.png` });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await panel.getByRole("button", { name: "Сохранить роли" }).click();
  await page.getByText("Сохранено").first().waitFor({ timeout: 10000 }).catch(() => {});
  r.check("«Сохранено» и роли в строке списка", (await page.getByRole("row", { name: /Новичок Демо/ }).innerText()).includes("Директор"));
  await page.waitForTimeout(1500);
  let erpRoles = "";
  try {
    erpRoles = compose("exec", "-T", "erp-backend", "python", "manage.py", "shell", "-c",
      "from accounts.models import CompanyMember as M; m=M.objects.get(user__email='newbie@demo.example'); print(sorted(m.company_roles.values_list('name',flat=True)))").trim().split("\n").pop();
  } catch (e) {
    erpRoles = String(e).slice(0, 100);
  }
  r.check("в ERP у новичка роли «Финансы» и «Руководитель» (провижининг CRM → ERP)", /Руководитель/.test(erpRoles) && /Финансы/.test(erpRoles), erpRoles);
  // открытая ранее сессия новичка
  await nb.page.reload();
  await nb.page.waitForTimeout(1500);
  r.note("сессия новичка, открытая до смены ролей, после reload", `${nb.page.url()} :: rail=${(await railTexts(nb.page).catch(() => [])).join(",")}`);
  await screen(nb.page, r, "newbie-session-after-role-change", { widths: [1440] });
  await nb.ctx.close();
  // повторный вход
  const nb2 = await newPage(browser);
  await loginOk(nb2.page, "newbie@demo.example", newbiePw);
  const after = await railTexts(nb2.page);
  r.check("после повторного входа новичок видит новые модули (включая Admin)", same(after, modulesFor(["ACCOUNTANT", "DIRECTOR"])), `${after.join(",")} / ожидание ${modulesFor(["ACCOUNTANT", "DIRECTOR"]).join(",")}`);
  await nb2.page.goto("/dashboard/summary");
  await nb2.page.getByRole("heading", { level: 1 }).waitFor();
  r.check("/dashboard/summary (только DIRECTOR/ACCOUNTANT-read) открывается", (await nb2.page.getByRole("heading", { level: 1 }).innerText()) !== "Нет доступа", await nb2.page.getByRole("heading", { level: 1 }).innerText());
  await screen(nb2.page, r, "newbie-after-grant", { widths: [1440, 1280] });
  await nb2.page.goto("/admin/org");
  await nb2.page.getByRole("heading", { level: 1 }).waitFor();
  r.check("новичок-директор: Оргструктура открывается (чтение), без кнопки «Пригласить сотрудника»", (await nb2.page.getByRole("heading", { level: 1 }).innerText()) === "Оргструктура" && (await nb2.page.getByText("Пригласить сотрудника").count()) === 0);
  await nb2.ctx.close();

  // директор — только чтение
  const d = await newPage(browser);
  await loginOk(d.page, USERS.director.email, USERS.director.pw);
  await d.page.goto("/admin/org");
  await d.page.getByRole("heading", { level: 1 }).waitFor();
  await d.page.getByRole("link", { name: /Открыть карточку: Менеджер Демо/ }).waitFor({ timeout: 10000 }).catch(() => {});
  const listOk = (await d.page.getByRole("link", { name: /Открыть карточку/ }).count()) >= 5;
  r.check("директор читает список сотрудников (CRM-01c)", listOk, `карточек=${await d.page.getByRole("link", { name: /Открыть карточку/ }).count()}; h1=${await d.page.getByRole("heading", { level: 1 }).innerText()}; текст=${(await d.page.getByRole("main").innerText()).replace(/\n+/g, " | ").slice(0, 200)}`);
  await d.page.getByRole("link", { name: /Открыть карточку: Менеджер Демо/ }).click();
  const dp = d.page.locator(PANEL);
  await dp.getByRole("heading", { level: 3, name: "Менеджер Демо" }).waitFor();
  r.check("директор: в карточке нет чекбоксов и кнопки «Сохранить роли»", (await dp.getByRole("checkbox").count()) === 0 && (await dp.getByRole("button", { name: "Сохранить роли" }).count()) === 0);
  r.check("директор: текст «Только просмотр…»", (await dp.getByText(/Только просмотр/).count()) === 1);
  r.check("директор: нет «Пригласить сотрудника»", (await d.page.getByText("Пригласить сотрудника").count()) === 0);
  await screen(d.page, r, "org-director-readonly", { narrow: true });
  // API: запись директору запрещена
  const csrf = (await d.ctx.cookies()).find((c) => c.name === "rt_pf_csrf")?.value ?? "";
  const resp = await d.page.request.patch("/api/v1/admin/users/2", { headers: { "x-csrf-token": csrf, "content-type": "application/json" }, data: { roles: ["MANAGER", "SUPPLY"] } });
  r.check("директор: PATCH /api/v1/admin/users/2 → 403 (BFF)", resp.status() === 403, `${resp.status()} ${(await resp.text()).slice(0, 150)}`);
  await d.ctx.close();

  // последний администратор. Сейчас админов двое: admin и multi
  const mu = await newPage(browser);
  await loginOk(mu.page, USERS.multi.email, USERS.multi.pw);
  const muBefore = (await mu.page.request.get("/api/v1/admin/users")).status();
  await spaGoto(page, "/admin/org");
  await page.getByRole("link", { name: /Открыть карточку: Универсал Демо/ }).click();
  await panel.getByRole("heading", { level: 3, name: "Универсал Демо" }).waitFor();
  await panel.getByRole("checkbox", { name: /^Администратор/ }).uncheck();
  r.check("пока админа два — снять роль у второго можно (кнопка активна)", await panel.getByRole("button", { name: "Сохранить роли" }).isEnabled());
  await panel.getByRole("button", { name: "Сохранить роли" }).click();
  await page.getByText("Сохранено").first().waitFor({ timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(1500);
  // открытая сессия бывшего админа: BFF держит роли сессии до повторного входа, CRM своё право проверяет сам
  const muMe = await (await mu.page.request.get("/api/v1/me")).json();
  const muAdmin = await mu.page.request.get("/api/v1/admin/users");
  r.note("сессия бывшего админа (multi), открытая до снятия роли, через ~2 с: до/после", `GET /admin/users: ${muBefore} → ${muAdmin.status()} ${(await muAdmin.text()).slice(0, 120)}; /me.roles=${JSON.stringify(muMe.roles ?? muMe.me?.roles)} modules=${JSON.stringify(muMe.modules ?? muMe.me?.modules)}`);
  await mu.page.reload();
  await mu.page.waitForTimeout(1000);
  r.note("та же сессия после reload — рейл", (await railTexts(mu.page).catch(() => [])).join(","));
  await screen(mu.page, r, "stale-session-after-demotion", { widths: [1440] });
  const demotedAt = Date.now() - 1500;
  await page.getByRole("link", { name: /Открыть карточку: Админ Демо/ }).click();
  await panel.getByRole("heading", { level: 3, name: "Админ Демо" }).waitFor();
  await panel.getByRole("checkbox", { name: /^Администратор/ }).uncheck();
  const note = panel.getByText("Вы единственный администратор: снять роль «Администратор» нельзя. Сначала назначьте администратором другого сотрудника.");
  await page.waitForTimeout(400);
  r.check("снятие последней роли ADMIN у себя: понятный текст", (await note.count()) === 1, (await panel.innerText()).replace(/\n+/g, " | ").slice(-400));
  r.check("кнопки «Сохранить роли» и «Отключить сотрудника» неактивны", (await panel.getByRole("button", { name: "Сохранить роли" }).isDisabled()) && (await panel.getByRole("button", { name: "Отключить сотрудника" }).isDisabled()));
  for (const w of [1440, 1280]) {
    await page.setViewportSize({ width: w, height: 1100 });
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${SHOTS}/s6-org-last-admin-${w}.png` });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await screen(page, r, "org-last-admin", { widths: [390] });
  // тот же запрет на уровне BFF/CRM
  const csrfA = (await ctx.cookies()).find((c) => c.name === "rt_pf_csrf")?.value ?? "";
  const meA = await (await page.request.get("/api/v1/me")).json();
  const selfId = meA.me?.id ?? meA.id;
  const api = await page.request.patch(`/api/v1/admin/users/${selfId}`, { headers: { "x-csrf-token": csrfA, "content-type": "application/json" }, data: { roles: ["DIRECTOR"] } });
  r.check("API: PATCH своих ролей без ADMIN → 409 LAST_ADMIN", api.status() === 409 && /LAST_ADMIN/.test(await api.text()), `${api.status()} ${(await api.text()).slice(0, 200)}`);
  await panel.getByRole("checkbox", { name: /^Администратор/ }).check();
  r.check("флажок возвращён — запрет снят", (await note.count()) === 0);

  // приглашение: форма и состояние после результата
  await page.getByRole("navigation", { name: "Разделы модуля" }).getByRole("link", { name: "Пригласить сотрудника" }).click();
  await panel.getByRole("heading", { level: 3, name: "Пригласить сотрудника" }).waitFor();
  await panel.getByRole("button", { name: "Отправить приглашение" }).click();
  await page.waitForTimeout(400);
  r.check("пустая форма: подсказки по полям и ролям", (await panel.getByText("Укажите имя и фамилию").count()) === 1 && (await panel.getByText("Выберите хотя бы одну роль.").count()) === 1);
  await panel.getByLabel("Имя и фамилия").fill("Проверка Формы");
  await panel.getByLabel("Электронная почта").fill(`form-${Date.now() % 100000}@demo.example`);
  await panel.getByRole("checkbox", { name: /^Директор/ }).check();
  await panel.getByRole("button", { name: "Отправить приглашение" }).click();
  await page.waitForTimeout(2500);
  r.note("результат приглашения (SMTP не подключён)", (await panel.innerText()).replace(/\n+/g, " | ").slice(-350));
  await screen(page, r, "invite-result-not-sent", { widths: [1440, 1280] });
  // что остаётся на экране после «письмо не отправлено»: форма с введёнными данными и активной кнопкой?
  const stillForm = await panel.getByRole("button", { name: "Отправить приглашение" }).isEnabled().catch(() => false);
  r.note("после «письмо не отправлено»: форма осталась, кнопка «Отправить приглашение» активна", String(stillForm));
  await page.getByRole("navigation", { name: "Разделы модуля" }).getByRole("link", { name: "Пригласить сотрудника" }).click();
  await page.waitForTimeout(500);
  const stale = {
    name: await panel.getByLabel("Имя и фамилия").inputValue().catch(() => null),
    email: await panel.getByLabel("Электронная почта").inputValue().catch(() => null),
    director: await panel.getByRole("checkbox", { name: /^Директор/ }).isChecked().catch(() => null),
  };
  r.check("повторное «Пригласить сотрудника» после результата очищает форму", !stale.name && !stale.email && !stale.director, JSON.stringify(stale));
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.screenshot({ path: `${SHOTS}/s6-invite-form-reopened-1440.png` });
  await page.setViewportSize({ width: 1440, height: 900 });
  await panel.getByRole("button", { name: "Отправить приглашение" }).click();
  await page.waitForTimeout(1500);
  r.note("повторная отправка той же формы", (await panel.getByText(/уже есть|не отправлен/).allInnerTexts()).join(" | ") || (await panel.innerText()).replace(/\n+/g, " | ").slice(-200));
  await spaGoto(page, "/admin/org");
  // та же открытая сессия бывшего админа через минуту: BFF перечитывает профиль CRM не реже раза в 60 с (PROFILE_TTL_SECONDS)
  const wait = 63000 - (Date.now() - demotedAt);
  if (wait > 0) await page.waitForTimeout(wait);
  const muMe2 = await (await mu.page.request.get("/api/v1/me")).json();
  const roles2 = muMe2.roles ?? muMe2.me?.roles;
  r.check("сессия бывшего админа сама получает новые роли в пределах минуты (без повторного входа)", JSON.stringify(roles2) === '["MANAGER"]', `roles=${JSON.stringify(roles2)} через ${Math.round((Date.now() - demotedAt) / 1000)} с`);
  const muAdmin2 = await mu.page.request.get("/api/v1/admin/users");
  r.check("и в BFF права Admin сняты (403, source=bff)", muAdmin2.status() === 403 && /"source":"bff"/.test(await muAdmin2.text()), `${muAdmin2.status()}`);
  await mu.page.reload();
  await mu.page.waitForTimeout(1000);
  r.check("после перезагрузки рейл без Admin", !(await railTexts(mu.page)).includes("Admin"));
  await mu.ctx.close();
  // вернуть multi роль ADMIN (прочие сценарии), отключить служебного form@
  await spaGoto(page, "/admin/org");
  await page.getByRole("link", { name: /Открыть карточку: Универсал Демо/ }).click();
  await panel.getByRole("heading", { level: 3, name: "Универсал Демо" }).waitFor();
  await panel.getByRole("checkbox", { name: /^Администратор/ }).check();
  await panel.getByRole("button", { name: "Сохранить роли" }).click();
  await page.getByText("Сохранено").first().waitFor({ timeout: 10000 }).catch(() => {});
  r.note("ошибки консоли", page.consoleErrors.join(" ;; ") || "нет");
  await ctx.close();
  r.save();
  return r;
};

// 11 (дополнительно к списку runbook). Dashboard · Моя очередь менеджера на данных CRM: лид с сайта без менеджера.
scenarios.s11 = async (browser) => {
  const r = new Report("s11");
  const { ctx, page } = await newPage(browser);
  await loginOk(page, USERS.manager.email, USERS.manager.pw);
  const main = page.getByRole("main");
  const row = main.getByRole("link", { name: /Открыть: Взять в работу лида L-0002/ });
  await row.waitFor({ timeout: 10000 }).catch(() => {});
  r.check("очередь менеджера: строка «Взять в работу лида L-0002» (лид с сайта в CRM)", (await row.count()) === 1, (await main.innerText()).replace(/\n+/g, " | ").slice(0, 300));
  r.check("подзаголовок: «Менеджер · … · 1 решение»", /Менеджер · .* · 1 решение/.test(await main.innerText()), (await main.innerText()).split("\n").slice(0, 3).join(" | "));
  const cards = await main.getByRole("region", { name: "Счётчики очереди" }).getByRole("link").allInnerTexts();
  r.note("карточки счётчиков", cards.map((t) => t.replace(/\n+/g, " ")).join(" || "));
  const menuQ = await page.getByRole("navigation", { name: "Разделы модуля" }).getByRole("link", { name: /^Моя очередь/ }).getAttribute("aria-label").catch(() => null);
  r.note("пункт меню «Моя очередь» (бейдж)", String(menuQ));
  await screen(page, r, "manager-queue", { narrow: true });
  await row.click();
  await page.waitForTimeout(700);
  const url = decodeURIComponent(page.url());
  r.check("«Открыть» ведёт на лид: /crm/leads?lead=L-0002&panel=open&tab=card", /\/crm\/leads\?lead=L-0002&panel=open&tab=card/.test(url), url);
  r.note("страница лида (P2-заглушка)", (await page.getByRole("heading", { level: 1 }).innerText()) + " :: боковое окно " + ((await page.getByRole("complementary", { name: "Боковое окно" }).count()) ? "открыто" : "скрыто"));
  // поиск лида
  await page.getByRole("combobox", { name: "Глобальный поиск" }).fill("Пётр Сайт");
  await page.waitForTimeout(1500);
  r.check("⌘K находит лид по имени: L-0002", (await page.getByRole("option", { name: /Пётр Сайт/ }).count()) >= 1, (await page.getByRole("listbox").innerText().catch(() => "")).replace(/\n+/g, " | "));
  await screen(page, r, "search-lead", { widths: [1440, 1280] });
  await ctx.close();
  // роль без очереди: пустая очередь словами SPEC-v3 §7.1 (снабженец)
  const s = await newPage(browser);
  await loginOk(s.page, USERS.supply.email, USERS.supply.pw);
  r.check("пустая очередь снабженца: «Решений от вас пока не требуется» + текст SPEC-v3 §7.1", (await s.page.getByText("Решений от вас пока не требуется").count()) === 1 && (await s.page.getByText("Новые письма приходят из CRM, черновики КП — из ERP, служебки — от сотрудников.").count()) === 1);
  await screen(s.page, r, "supply-empty-queue", { widths: [1440, 1280] });
  await s.ctx.close();
  r.save();
  return r;
};

const redis = (cmd) => compose("exec", "-T", "redis", "sh", "-c", `redis-cli --no-auth-warning -a "$REDIS_PASSWORD" -n 3 ${cmd}`).trim();

// 9. Выход: сессия гасится (после выхода /api/v1/me → 401).
scenarios.s9 = async (browser) => {
  const r = new Report("s9");
  const { ctx, page } = await newPage(browser);
  await loginOk(page, USERS.manager.email, USERS.manager.pw);
  const cookies = await ctx.cookies();
  const sid = cookies.find((c) => c.name === "rt_pf_session")?.value ?? "";
  const csrf = cookies.find((c) => c.name === "rt_pf_csrf")?.value ?? "";
  r.check("после входа GET /api/v1/me → 200", (await page.request.get("/api/v1/me")).status() === 200);
  const keysBefore = redis("keys 'session:*'").split("\n").filter(Boolean).length;
  const hasKey = redis(`exists session:${sid}`);
  r.check("сессия лежит в Redis (БД 3, ключ session:<sid>)", hasKey === "1", `exists=${hasKey}; всего сессий=${keysBefore}`);
  // токены бэкендов из сессии (значения не печатаем): проверим, что после выхода CRM их отвергает
  let crmRefresh = "";
  try {
    const raw = JSON.parse(redis(`get session:${sid}`));
    r.note("поля сессии в Redis (только имена)", Object.keys(raw).join(","));
    crmRefresh = raw.crm?.refresh ?? raw.crm_refresh ?? raw.crm_refresh_token ?? raw.tokens?.crm?.refresh ?? "";
  } catch (e) {
    r.note("не удалось разобрать сессию", String(e).slice(0, 80));
  }
  await page.goto("/crm/leads");
  await page.getByRole("heading", { level: 1 }).waitFor();
  await signOut(page);
  r.check("после «Выйти» — экран входа", /\/login/.test(page.url()), page.url());
  const me = await page.request.get("/api/v1/me");
  r.check("после выхода GET /api/v1/me → 401", me.status() === 401, `${me.status()} ${(await me.text()).slice(0, 120)}`);
  const after = (await ctx.cookies()).find((c) => c.name === "rt_pf_session")?.value ?? "";
  r.check("cookie сессии удалена в браузере", !after, after ? "cookie осталась" : "нет");
  // повтор старой cookie «с другого клиента»
  const replay = await browser.newContext({ baseURL: BASE });
  const rq = replay.request;
  const rsp = await rq.get("/api/v1/me", { headers: { cookie: `rt_pf_session=${sid}` } });
  r.check("повтор старой cookie сессии → 401", rsp.status() === 401, `${rsp.status()}`);
  const rsp2 = await rq.get("/api/v1/notifications", { headers: { cookie: `rt_pf_session=${sid}` } });
  r.check("повтор старой cookie на данных (/notifications) → 401", rsp2.status() === 401, `${rsp2.status()}`);
  await replay.close();
  r.check("ключ session:<sid> в Redis удалён", redis(`exists session:${sid}`) === "0");
  if (crmRefresh) {
    const resp = await fetch(`${process.env.QA_CRM ?? "http://127.0.0.1:18000"}/api/v1/auth/refresh`, { method: "POST", headers: { cookie: `rt_refresh=${crmRefresh}` } });
    r.check("refresh-токен CRM из погашенной сессии отвергнут CRM (401)", resp.status === 401, `status=${resp.status}`);
  } else {
    r.note("refresh-токен CRM из сессии не найден по известным именам полей — проверка отзыва в CRM не выполнена");
  }
  // назад по истории не показывает данные
  await page.goBack().catch(() => {});
  await page.waitForTimeout(800);
  r.check("кнопка «Назад» после выхода не открывает защищённый экран (уходит на вход)", /\/login/.test(page.url()), page.url());
  await screen(page, r, "after-logout", { narrow: true });
  void csrf;
  await ctx.close();
  r.save();
  return r;
};

// 10. Устойчивость: ERP остановлена — Платформа работает с плашкой «ERP не отвечает», CRM-часть жива.
scenarios.s10 = async (browser) => {
  const r = new Report("s10");
  const d = await newPage(browser);
  await loginOk(d.page, USERS.director.email, USERS.director.pw);
  const m = await newPage(browser);
  await loginOk(m.page, USERS.manager.email, USERS.manager.pw);
  r.check("до остановки плашки «ERP не отвечает» нет", (await d.page.getByText(/ERP не отвечает/).count()) === 0);
  compose("stop", "erp-backend");
  const t0 = Date.now();
  r.note("erp-backend остановлен", new Date().toISOString());
  await d.page.waitForTimeout(3000);
  await d.page.reload();
  await d.page.getByRole("heading", { level: 1 }).waitFor({ timeout: 20000 });
  const banner = d.page.getByRole("main").getByText(/ERP не отвечает/);
  const tb = Date.now();
  const shownAt = await banner.first().waitFor({ timeout: 45000 }).then(() => Math.round((Date.now() - t0) / 1000), () => null);
  r.check("Платформа открывается; в основном окне плашка «ERP не отвечает…» (ждём до 45 с — кэш снимка 8 с, опрос 30 с)", shownAt !== null, shownAt !== null ? `плашка появилась через ${shownAt} с после остановки ERP` : (await d.page.getByRole("main").innerText()).replace(/\n+/g, " | ").slice(0, 300));
  r.note("текст плашки", (await banner.allInnerTexts()).join(" || "));
  await screen(d.page, r, "erp-down-dashboard", { narrow: true });
  const h = await (await d.page.request.get("/api/v1/health")).json();
  r.check("/api/v1/health: CRM ok, ERP недоступна, общий статус degraded", /degraded|unavailable/.test(JSON.stringify(h)) , JSON.stringify(h).slice(0, 250));
  const me = await d.page.request.get("/api/v1/me");
  r.check("/api/v1/me (сессия) отвечает 200", me.status() === 200);
  const notif = await (await d.page.request.get("/api/v1/notifications")).json();
  r.check("/notifications: sources.erp ≠ ok, sources.crm = ok", notif.sources?.erp !== "ok" && notif.sources?.crm === "ok", JSON.stringify(notif.sources));
  // навигация по модулям не ломается
  for (const route of ["/crm/clients", "/eds/inbox", "/admin/org"]) {
    await d.page.goto(route);
    await d.page.getByRole("heading", { level: 1 }).waitFor();
    r.check(`при ERP-сбое ${route} открывается без белого экрана`, (await d.page.getByRole("heading", { level: 1 }).innerText()).length > 0, await d.page.getByRole("heading", { level: 1 }).innerText());
  }
  await screen(d.page, r, "erp-down-org", { widths: [1440, 1280] });
  // поиск: CRM-часть жива
  const sr = await (await m.page.request.get("/api/v1/search?q=%D0%94%D0%B5%D0%BC%D0%BE%20%D0%9A%D0%BB%D0%B8%D0%B5%D0%BD%D1%82")).json();
  r.check("поиск при ERP-сбое: клиент CRM найден, sources.erp ≠ ok", (sr.groups ?? []).some((g) => g.module === "crm") && sr.sources?.erp !== "ok", JSON.stringify(sr).slice(0, 300));
  await m.page.reload();
  await m.page.getByRole("heading", { level: 1 }).waitFor();
  await m.page.getByRole("combobox", { name: "Глобальный поиск" }).fill("Демо Клиент");
  await m.page.waitForTimeout(2000);
  await screen(m.page, r, "erp-down-search-crm", { widths: [1440, 1280] });
  // CRM и ее домен живы
  const crmH = await fetch(`${process.env.QA_CRM ?? "http://127.0.0.1:18000"}/health`);
  r.check("CRM /health → 200 (CRM-часть жива)", crmH.status === 200, `${crmH.status}`);
  const viaCaddy = await fetch(`${BASE.replace("platform.", "crm.")}/health`);
  r.check("crm.localhost через Caddy /health → 200", viaCaddy.status === 200, `${viaCaddy.status}`);
  // новый вход при недоступной ERP (Q-PLT-10-1 п.1)
  const s = await newPage(browser);
  await loginOk(s.page, USERS.supply.email, USERS.supply.pw);
  await s.page.waitForTimeout(2000);
  r.check("новый вход при остановленной ERP проходит; плашка есть", (await s.page.getByRole("main").getByText(/ERP не отвечает/).count()) >= 1);
  await screen(s.page, r, "erp-down-fresh-login", { widths: [1440] });
  await s.ctx.close();
  // держим минуту
  const left = 60000 - (Date.now() - t0);
  if (left > 0) await d.page.waitForTimeout(left);
  r.note("ERP была недоступна, секунд", String(Math.round((Date.now() - t0) / 1000)));
  await d.page.goto("/dashboard/queue");
  await d.page.getByRole("heading", { level: 1 }).waitFor();
  await d.page.getByRole("main").getByText(/ERP не отвечает/).first().waitFor({ timeout: 20000 }).catch(() => {});
  compose("start", "erp-backend");
  const t1 = Date.now();
  let up = false;
  while (Date.now() - t1 < 150000) {
    try {
      const rr = await fetch(`${BASE.replace("platform.", "erp.")}/health`);
      if (rr.status === 200) { up = true; break; }
    } catch { /* ещё поднимается */ }
    await new Promise((x) => setTimeout(x, 2000));
  }
  r.check("erp-backend снова отвечает /health", up, `${Math.round((Date.now() - t1) / 1000)} с`);
  // восстановление без повторного входа: опрос 30 с на той же странице, затем перезагрузка
  const t2 = Date.now();
  const goneAt = await d.page.getByRole("main").getByText(/ERP не отвечает/).first().waitFor({ state: "detached", timeout: 60000 }).then(() => Math.round((Date.now() - t2) / 1000), () => null);
  r.check("после возврата ERP плашка исчезает сама (опрос), без перезагрузки и повторного входа", goneAt !== null, goneAt !== null ? `через ${goneAt} с после возврата ERP /health = 200` : "плашка не исчезла за 60 с");
  await d.page.reload();
  await d.page.getByRole("heading", { level: 1 }).waitFor();
  await d.page.waitForTimeout(3000);
  let gone = (await d.page.getByRole("main").getByText(/ERP не отвечает/).count()) === 0;
  r.check("после перезагрузки плашки нет (повторный вход не потребовался)", gone);
  await d.page.waitForTimeout(500);
  const notif2 = await (await d.page.request.get("/api/v1/notifications")).json();
  r.check("/notifications: sources.erp = ok", notif2.sources?.erp === "ok", JSON.stringify(notif2.sources));
  await screen(d.page, r, "erp-restored", { widths: [1440] });
  await d.ctx.close();
  await m.ctx.close();
  r.save();
  return r;
};

const names = process.argv.slice(2);
const browser = await launch();
let failed = 0;
for (const n of names) {
  if (!scenarios[n]) throw new Error(`нет сценария ${n}`);
  console.log(`=== ${n} ===`);
  const rep = await scenarios[n](browser);
  failed += rep.rows.filter((x) => x.ok === false).length;
}
await browser.close();
console.log(`\nbase=${BASE}; проверок не пройдено: ${failed}`);
