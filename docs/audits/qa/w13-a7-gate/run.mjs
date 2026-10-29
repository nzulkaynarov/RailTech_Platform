// W13-A7: сценарии гейта C2a «Паритет Admin» против живого стенда (Caddy -> BFF -> CRM/ERP/EDS). Запуск:
//   QA_OUT=<каталог вне репозитория> QA_COMPOSE=<обёртка docker compose проекта rt-c2> node docs/audits/qa/w13-a7-gate/run.mjs s1 s2 ...
// Пароли генерируются на лету и лежат в QA_OUT/state.json (вне репозитория). Снимки — docs/screens/w13-a7-gate/.
// Сценарии идут по пунктам runbook wave13-c2-admin.md §3 A7 (1…8); пункт 9 (замер шины) — measure.sh из W13-A0.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  Report, launch, newPage, login, loginOk, signOut, openAvatarMenu, spaGoto, screen, shot, toastsGone, bff, state, saveState, secret, motionEnd,
} from "./lib.mjs";

const compose = (...args) => {
  const w = process.env.QA_COMPOSE;
  if (!w) throw new Error("QA_COMPOSE не задан: путь к обёртке docker compose проекта rt-c2");
  return execFileSync(w, args, { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
};
const ADMIN_EMAIL = "admin.demo@demo.example";
const PANEL = "#pf-context-panel";
const scenarios = {};

/** Попытка шага: ошибка не обрывает сценарий, а фиксируется как FAIL со снимком. */
async function step(page, r, desc, fn) {
  try {
    await fn();
    return r.check(desc, true);
  } catch (e) {
    const msg = String(e.message ?? e).split("\n").slice(0, 3).join(" / ").slice(0, 400);
    r.check(desc, false, msg);
    await shot(page, r, `FAIL-${r.rows.length}`).catch(() => {});
    return false;
  }
}

// ---------------------------------------------------------------------------------------------------------------------
// 1. Первый запуск: /setup -> администратор по коду из логов crm-api -> мастер -> своя компания -> баннер из 5 шагов.
scenarios.s1 = async (browser) => {
  const r = new Report("s1");
  const { page } = await newPage(browser);
  const adminPw = secret("adm");
  saveState({ adminEmail: ADMIN_EMAIL, adminPw });

  await page.goto("/login");
  await step(page, r, "вход без администратора ведёт на «Первый запуск» (/setup)", async () => {
    await page.waitForURL(/\/setup$/);
    await page.getByRole("heading", { level: 1, name: "Первый запуск" }).waitFor();
    await page.getByText("Что произойдёт").waitFor();
  });
  await screen(page, r, "setup-form");

  const logs = compose("logs", "crm-api");
  const m = [...logs.matchAll(/"setup_code": "([^"]+)"/g)].pop();
  r.check("код первого запуска найден в журнале crm-api (строка setup_code_issued)", !!m);
  const code = m?.[1] ?? "";

  const fill = async (c, pw) => {
    await page.getByLabel("Код первого запуска").fill(c);
    await page.getByLabel("Имя и фамилия").fill("Демо Админов");
    await page.getByLabel("Электронная почта администратора").fill(ADMIN_EMAIL);
    await page.getByLabel("Пароль", { exact: true }).fill(pw);
    await page.getByLabel("Повторите пароль").fill(pw);
  };
  await fill("wrong-code-000000", adminPw);
  await page.getByRole("button", { name: "Создать администратора и войти" }).click();
  await step(page, r, "неверный код — понятное сообщение, форма остаётся", async () => {
    await page.getByRole("alert").filter({ hasText: /Код неверный/ }).waitFor({ timeout: 8000 });
  });
  await shot(page, r, "setup-wrong-code", { mask: [page.getByLabel("Код первого запуска"), page.getByLabel("Пароль", { exact: true }), page.getByLabel("Повторите пароль")] });

  await fill(code, adminPw);
  await page.getByRole("button", { name: "Создать администратора и войти" }).click();
  await step(page, r, "верный код: администратор создан, вход выполнен, мастер «Ваша компания»", async () => {
    await page.waitForURL(/\/admin\/setup$/, { timeout: 30000 });
    await page.getByRole("heading", { level: 2, name: "Ваша компания" }).waitFor({ timeout: 15000 });
  });
  await toastsGone(page);
  await screen(page, r, "wizard-company");
  r.note("ошибки консоли / ответы 5xx на шаге администратора", `${page.consoleErrors.join(" | ")} ${page.failed.join(" | ")}`);
  r.save();
};


// ---------------------------------------------------------------------------------------------------------------------
// 2a. «Подключить ERP» (сопряжение без кода: bootstrap по PLATFORM_SSO_SECRET) и «Проверить» — зелёное. Нужно до шага «Своя компания».
const tile = (page, key) => page.locator(`article[data-card="${key}"]`);
const side = (page) => page.locator(PANEL);
async function openCard(page, card) {
  await spaGoto(page, card ? `/admin/integrations?card=${card}&panel=open` : "/admin/integrations");
  await page.getByRole("heading", { level: 1, name: "Внешние интеграции" }).waitFor();
  if (card) await side(page).getByRole("heading", { level: 3 }).first().waitFor({ timeout: 15000 });
  await page.waitForTimeout(800);
  await page.locator(".ant-skeleton").first().waitFor({ state: "detached", timeout: 15000 }).catch(() => {});
}

scenarios.s2erp = async (browser) => {
  const r = new Report("s2erp");
  const { page } = await newPage(browser);
  const st = state();
  await loginOk(page, st.adminEmail, st.adminPw);
  await openCard(page, "erp");
  await shot(page, r, "erp-before");
  const panel = side(page);
  await panel.getByRole("button", { name: /Подключить ERP/ }).first().click();
  const form = panel.getByRole("form", { name: "Подключить ERP" });
  await step(page, r, "форма сопряжения с блоком «Что произойдёт»", async () => {
    await form.getByRole("group", { name: "Что произойдёт" }).waitFor();
  });
  await form.getByLabel("Адрес ERP").fill("http://erp-backend:8000");
  await form.getByLabel("Ваш пароль администратора").fill("not-the-password-000");
  await form.getByRole("button", { name: "Подключить ERP" }).click();
  await step(page, r, "неверный пароль администратора — понятная ошибка, не 500", async () => {
    await form.getByRole("alert").filter({ hasText: /Пароль указан неверно/ }).waitFor({ timeout: 10000 });
  });
  await shot(page, r, "erp-pair-wrong-password", { mask: [form.getByLabel("Ваш пароль администратора")] });
  await form.getByLabel("Ваш пароль администратора").fill(st.adminPw);
  await form.getByRole("button", { name: "Подключить ERP" }).click();
  await step(page, r, "сопряжение выполнено (без кода), ключи в маске", async () => {
    await panel.getByText(/Сопряжение выполнено/).waitFor({ timeout: 30000 });
  });
  await toastsGone(page);
  r.note("карточка ERP после сопряжения", (await panel.innerText()).replace(/\n+/g, " | ").slice(0, 500));
  await screen(page, r, "erp-paired", { mask: [] });
  await panel.getByRole("button", { name: "Проверить связь" }).click();
  await step(page, r, "«Проверить связь»: ERP отвечает", async () => {
    await panel.getByText("ERP отвечает", { exact: true }).waitFor({ timeout: 20000 });
  });
  await openCard(page, null);
  await step(page, r, "плитка ERP: статус «Работает»", async () => {
    await tile(page, "erp").getByText("Работает", { exact: true }).waitFor({ timeout: 15000 });
  });
  r.note("ошибки консоли / ответы 5xx", `${page.consoleErrors.join(" | ")} ${page.failed.join(" | ")}`);
  r.save();
};

// 1b. Своя компания (ERP setup/company) и баннер чек-листа из пяти шагов; после сопряжения ERP.
scenarios.s1b = async (browser) => {
  const r = new Report("s1b");
  const { page } = await newPage(browser);
  const st = state();
  await loginOk(page, st.adminEmail, st.adminPw);
  await spaGoto(page, "/admin/setup");
  await page.getByRole("heading", { level: 1, name: "Первый запуск" }).waitFor();
  await page.waitForTimeout(1500);
  // доступ к ERP выдаётся новому администратору задачей CRM с задержкой — ждём до ~3 мин, нажимая «Проверить снова»
  const t0 = Date.now();
  let formShown = false;
  while (Date.now() - t0 < 200000) {
    if (await page.getByLabel("Название компании").isVisible().catch(() => false)) { formShown = true; break; }
    const again = page.getByRole("button", { name: "Проверить снова" });
    if (await again.isVisible().catch(() => false)) await again.click();
    await page.waitForTimeout(8000);
  }
  r.check("форма «Ваша компания» стала доступна после сопряжения ERP", formShown, `ожидание ${Math.round((Date.now() - t0) / 1000)} с`);
  await shot(page, r, "wizard-company-form");
  if (formShown) {
    await page.getByLabel("Название компании").fill("ООО Демо Рельс Сервис");
    await page.getByLabel("ИНН (необязательно)").fill("000");
    await page.getByRole("button", { name: "Создать компанию" }).click();
    await step(page, r, "неверный ИНН — ошибка у поля словами", async () => {
      await page.getByText(/ИНН/).nth(1).waitFor({ timeout: 10000 });
    });
    await shot(page, r, "wizard-company-inn-error");
    await page.getByLabel("ИНН (необязательно)").fill("305001234");
    await page.getByRole("button", { name: "Создать компанию" }).click();
    await step(page, r, "компания создана", async () => {
      await page.getByText("Своя компания создана.").waitFor({ timeout: 30000 });
    });
  }
  await toastsGone(page);
  const steps = page.getByRole("list", { name: "Шаги настройки" });
  await step(page, r, "чек-лист: пять шагов", async () => {
    await steps.getByRole("listitem").nth(4).waitFor();
    if ((await steps.getByRole("listitem").count()) !== 5) throw new Error("не пять шагов");
  });
  r.note("прогресс чек-листа", await page.getByText(/Готово \d из 5/).first().innerText().catch(() => "—"));
  await screen(page, r, "wizard-after-company");
  await spaGoto(page, "/admin/org");
  const banner = page.getByRole("region", { name: "Настройка Платформы" });
  await step(page, r, "баннер «Настройка Платформы» на других экранах", async () => {
    await banner.waitFor({ timeout: 10000 });
  });
  r.note("текст баннера", (await banner.innerText().catch(() => "")).replace(/\n+/g, " | "));
  await screen(page, r, "banner-org");
  await openAvatarMenu(page).catch(() => {});
  r.save();
};


// ---------------------------------------------------------------------------------------------------------------------
// 2. Внешние интеграции: обзор, каждая карточка, «Проверить» без настоящих токенов (честные ответы), модели ИИ, расходы, бэкапы.
const pwField = (form) => form.getByLabel("Ваш пароль администратора");

scenarios.s2 = async (browser) => {
  const r = new Report("s2");
  const { page } = await newPage(browser);
  const st = state();
  await loginOk(page, st.adminEmail, st.adminPw);
  const panel = side(page);

  // --- обзор и статусы словом
  await openCard(page, null);
  await step(page, r, "обзор: «Требует внимания» и восемь карточек со статусом словом", async () => {
    await page.getByRole("heading", { level: 2, name: "Требует внимания" }).waitFor();
    if ((await page.locator("article[data-card]").count()) !== 8) throw new Error(`карточек ${await page.locator("article[data-card]").count()}`);
  });
  const words = [];
  for (const key of ["erp", "telegram", "mail", "services", "models", "spend", "storage", "system"]) {
    words.push(`${key}: ${(await tile(page, key).innerText()).split("\n").slice(0, 2).join(" / ")}`);
  }
  r.note("статусы карточек на обзоре", words.join(" ;; "));
  await screen(page, r, "overview");

  // --- «Проверить» на каждой плитке (без настоящих токенов — честный результат, не 500)
  for (const key of ["telegram", "mail", "services", "models", "storage", "system", "spend"]) {
    await openCard(page, null);
    const t = tile(page, key);
    await t.getByRole("button", { name: /^(Проверить|Обновить)/ }).click();
    await page.waitForTimeout(3500);
    const txt = (await t.innerText()).replace(/\n+/g, " | ");
    r.check(`плитка «${key}»: «Проверить/Обновить» отработала, результат словами`, /Проверено|Проверок|Обновлено|Расход|Данные обновлены|ещё не настроена|не отвечает/.test(txt) && !page.failed.some((x) => /^(500|503|504) /.test(x)), txt.slice(0, 260));
  }

  // --- каждая карточка открывается; axe + снимки на 1440 и 390
  for (const key of ["erp", "telegram", "mail", "services", "models", "spend", "storage", "system"]) {
    await openCard(page, key);
    await screen(page, r, `card-${key}`, { narrow: true });
  }

  // --- Telegram: токен не принят — понятная ошибка
  await openCard(page, "telegram");
  await panel.getByRole("button", { name: /^(Задать|Сменить) токен/ }).click();
  const tgForm = panel.getByRole("form", { name: "Токен бота" });
  await tgForm.getByLabel("Токен бота", { exact: true }).fill("100200:" + secret("fakeTelegramToken").replace(/-/g, "x"));
  await pwField(tgForm).fill(st.adminPw);
  await shot(page, r, "telegram-token-form", { mask: [tgForm.getByLabel("Токен бота", { exact: true }), pwField(tgForm)] });
  await tgForm.getByRole("button", { name: "Сохранить токен" }).click();
  await page.waitForTimeout(6000);
  const tgAlert = (await tgForm.getByRole("alert").first().innerText().catch(() => "")) || (await panel.innerText()).slice(0, 300);
  r.check("Telegram: токен без настоящего бота — ошибка словами, не 500", page.failed.filter((x) => /^(500|503) .*integrations\/telegram/.test(x)).length === 0 && /Telegram/.test(tgAlert), tgAlert.replace(/\n+/g, " | ").slice(0, 300));
  await shot(page, r, "telegram-token-error", { mask: [tgForm.getByLabel("Токен бота", { exact: true }), pwField(tgForm)] });

  // --- Почта: «Проверить связь» и «Тестовое письмо» без SMTP — честный ответ
  await openCard(page, "mail");
  const mailCheck = panel.getByRole("button", { name: "Проверить связь" });
  const mailTest = panel.getByRole("button", { name: "Тестовое письмо" });
  const mailConfigured = !(await panel.getByText("Не настроена").first().isVisible().catch(() => false));
  if (!mailConfigured) {
    r.check("Почта без SMTP: «Проверить связь» и «Тестовое письмо» недоступны, а не падают", (await mailCheck.isDisabled()) && (await mailTest.isDisabled()), `check disabled=${await mailCheck.isDisabled()}, test disabled=${await mailTest.isDisabled()}`);
    await shot(page, r, "mail-unconfigured");
  } else {
    r.note("Почта уже настроена прогоном s2tail — ветку «без SMTP» см. в журнале первого прогона", "console-final-batch1.txt");
    await mailCheck.click();
    await page.waitForTimeout(6000);
    r.note("Почта · «Проверить связь» (SMTP настроен, сервер недоступен)", (await panel.innerText()).replace(/\n+/g, " | ").slice(0, 400));
  }
  r.note("Почта · состояние карточки", (await panel.innerText()).replace(/\n+/g, " | ").slice(0, 400));
  await panel.getByRole("button", { name: "Настроить SMTP" }).click();
  const smtp = panel.getByRole("form", { name: "Настройки SMTP" });
  await step(page, r, "SMTP: форма с «Что произойдёт»", async () => {
    await smtp.getByRole("group", { name: "Что произойдёт" }).waitFor();
  });
  await smtp.getByLabel("Сервер (хост)").fill("bad host");
  await pwField(smtp).fill(st.adminPw);
  await smtp.getByRole("button", { name: "Сохранить настройки" }).click();
  await step(page, r, "SMTP: некорректный сервер — ошибка словами у формы", async () => {
    await smtp.getByRole("alert").first().waitFor({ timeout: 10000 });
  });
  await shot(page, r, "mail-smtp-bad-host", { mask: [pwField(smtp)] });

  // --- Внешние сервисы: проверка живого, проверка упавшего, выключатель
  await openCard(page, "services");
  await panel.getByRole("button", { name: "Проверить сервис: Хранилище файлов (S3)" }).click();
  await page.waitForTimeout(3000);
  r.note("Сервисы · проверка S3", "см. снимок services-after-check");
  await panel.getByRole("button", { name: "Проверить сервис: Распознавание документов (docling)" }).click();
  await page.waitForTimeout(5000);
  await shot(page, r, "services-after-check");
  await panel.getByRole("button", { name: "Выключить сервис: Langfuse (журнал работы ИИ)" }).click();
  const off = panel.getByRole("form", { name: "Выключить сервис: Langfuse (журнал работы ИИ)" });
  await step(page, r, "выключатель сервиса: «Что произойдёт», причина, пароль", async () => {
    await off.getByRole("group", { name: "Что произойдёт" }).waitFor();
    await off.getByLabel("Причина (попадёт в журнал)").fill("гейт C2a: проверка выключателя");
    await pwField(off).fill(st.adminPw);
  });
  await shot(page, r, "services-disable-form", { mask: [pwField(off)] });
  await off.getByRole("button", { name: "Выключить сервис" }).click();
  await step(page, r, "сервис выключен вручную — виден в карточке", async () => {
    await panel.getByText("выключено вручную").waitFor({ timeout: 15000 });
  });
  await panel.getByRole("button", { name: "Включить сервис: Langfuse (журнал работы ИИ)" }).click();
  const on = panel.getByRole("form", { name: "Включить сервис: Langfuse (журнал работы ИИ)" });
  await pwField(on).fill(st.adminPw);
  await on.getByRole("button", { name: "Включить сервис" }).click();
  await step(page, r, "сервис включён обратно", async () => {
    await panel.getByText("выключено вручную").waitFor({ state: "detached", timeout: 15000 });
  });

  // --- Модели ИИ: список, проверка без ключа (честная ошибка), смена ключа с маской, сброс
  await openCard(page, "models");
  r.check("модели ИИ: список ролей (9 строк)", (await panel.getByRole("button", { name: /^Проверить модель/ }).count()) >= 8, `${await panel.getByRole("button", { name: /^Проверить модель/ }).count()}`);
  await panel.getByRole("button", { name: "Проверить модель: Диалог с клиентом" }).click();
  const chk = panel.getByRole("form", { name: "Проверка модели «Диалог с клиентом»" });
  await step(page, r, "проверка модели: предупреждение о платном запросе", async () => {
    await chk.getByRole("group", { name: "Что произойдёт" }).waitFor();
  });
  await chk.getByRole("button", { name: "Проверить модель" }).click();
  await page.waitForTimeout(9000);
  r.note("Модели · проверка без ключей", (await panel.innerText()).replace(/\n+/g, " | ").slice(0, 400));
  await shot(page, r, "models-check-no-key");
  const fakeKey = "fake-provider-key-" + secret("k").slice(2, 12);
  await panel.getByRole("button", { name: "Сменить модель: Квалификатор лида" }).click();
  const chg = panel.getByRole("form", { name: "Сменить модель: Квалификатор лида" });
  await chg.getByLabel("Ключ провайдера").fill(fakeKey);
  await pwField(chg).fill(st.adminPw);
  await shot(page, r, "models-change-form", { mask: [chg.getByLabel("Ключ провайдера"), pwField(chg)] });
  const prefilled = await chg.getByLabel("Модель", { exact: true }).inputValue();
  await chg.getByRole("button", { name: "Сменить модель" }).click();
  await page.waitForTimeout(5000);
  const firstAlert = (await chg.getByRole("alert").first().innerText().catch(() => "")).replace(/\n+/g, " | ");
  r.check("смена ключа без правки предзаполненной модели проходит", !firstAlert, `в поле «Модель» предзаполнено «${prefilled}»; ответ: ${firstAlert || "ок"}`);
  if (firstAlert) {
    await shot(page, r, "models-change-422-prefilled", { mask: [chg.getByLabel("Ключ провайдера"), pwField(chg)] });
    await chg.getByLabel("Модель", { exact: true }).fill(prefilled.replace(/^[a-z]+\//, ""));
    await chg.getByLabel("Ключ провайдера").fill(fakeKey);   // секретные поля после ошибки очищаются
    await pwField(chg).fill(st.adminPw);
    await chg.getByRole("button", { name: "Сменить модель" }).click();
    await page.waitForTimeout(8000);
  }
  const body = await page.locator("body").innerText();
  r.check("ключ провайдера на экране не появляется", !body.includes(fakeKey), "");
  r.note("Модели · смена с ключом", (await panel.innerText()).replace(/\n+/g, " | ").slice(0, 500));
  r.check("маска ключа «•••• ХХХХ» после смены", /••••\s*\w{4}/.test((await panel.innerText()).split("Квалификатор лида")[1] ?? ""), ((await panel.innerText()).split("Квалификатор лида")[1] ?? "").replace(/\n+/g, " | ").slice(0, 160));
  await shot(page, r, "models-after-change");
  const resetBtn = panel.getByRole("button", { name: "Сбросить модель: Квалификатор лида" });
  if (await resetBtn.isVisible().catch(() => false)) {
    await resetBtn.click();
    const rs = panel.getByRole("form", { name: "Сбросить модель: Квалификатор лида" });
    await pwField(rs).fill(st.adminPw);
    await rs.getByRole("button", { name: "Сбросить к значению по умолчанию" }).click();
    await step(page, r, "сброс модели к значению по умолчанию", async () => {
      await panel.getByText("Используется ключ из настроек сервера.").first().waitFor({ timeout: 15000 });
    });
  }

  // --- Расходы, бэкапы, состояние
  await openCard(page, "spend");
  await step(page, r, "расходы: бот и весь ансамбль, таблицы", async () => {
    await panel.getByRole("table", { name: "Провайдеры за сегодня" }).waitFor();
    await panel.getByRole("table", { name: "Расходы по группам" }).waitFor();
  });
  await openCard(page, "storage");
  await panel.getByRole("button", { name: "Сделать копию сейчас" }).click();
  const bk = panel.getByRole("form", { name: "Копия вне расписания" });
  await step(page, r, "копия вне расписания: «Что произойдёт»", async () => {
    await bk.getByRole("group", { name: "Что произойдёт" }).waitFor();
  });
  await panel.getByRole("button", { name: "Запросить копию" }).click();
  await page.waitForTimeout(4000);
  r.note("Бэкапы · «Запросить копию» без сервиса бэкапа", (await panel.innerText()).replace(/\n+/g, " | ").slice(0, 500));
  await shot(page, r, "storage-backup-request");
  await openCard(page, "system");
  await step(page, r, "состояние системы: список компонентов", async () => {
    await panel.getByRole("list", { name: "Состояние системы" }).waitFor();
  });
  r.note("ошибки консоли / ответы 5xx", `${page.consoleErrors.join(" | ")} ;; ${page.failed.join(" | ")}`);
  r.save();
};


// ---------------------------------------------------------------------------------------------------------------------
// 5a. Приглашения: по почте (почта не настроена — понятная ошибка) и без почты (временный пароль один раз, копирование);
// первый вход сотрудника с временным паролем -> обязательная смена. Сотрудники вымышленные, пароли — только в state.json.
const STAFF = [
  { key: "director", name: "Демо Директоров", email: "director.demo@demo.example", role: /^Директор/, position: "Директор" },
  { key: "manager", name: "Демо Менеджеров", email: "manager.demo@demo.example", role: /^Менеджер/, position: "Менеджер по продажам" },
  { key: "accountant", name: "Демо Бухгалтеров", email: "accountant.demo@demo.example", role: /^Бухгалтер/, position: "Бухгалтер" },
];

scenarios.s5a = async (browser) => {
  const r = new Report("s5a");
  const { page, ctx } = await newPage(browser);
  await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: new URL(process.env.QA_BASE ?? "http://platform.localhost:8097").origin });
  const st = state();
  await loginOk(page, st.adminEmail, st.adminPw);
  const panel = side(page);

  // по почте: SMTP не настроен
  await spaGoto(page, "/admin/org?invite=open&panel=open");
  await panel.getByRole("heading", { level: 3, name: "Пригласить сотрудника" }).waitFor();
  await panel.getByLabel("Имя и фамилия").fill("Демо Почтовый");
  await panel.getByLabel("Электронная почта").fill("mailtest.demo@demo.example");
  await panel.getByRole("checkbox", { name: /^Менеджер/ }).check();
  await panel.getByRole("button", { name: "Отправить приглашение" }).click();
  await step(page, r, "приглашение по почте без SMTP — понятная ошибка, а не 500", async () => {
    await panel.getByRole("alert").first().waitFor({ timeout: 15000 });
  });
  r.note("текст ошибки приглашения по почте", (await panel.getByRole("alert").first().innerText()).replace(/\n+/g, " | "));
  await shot(page, r, "invite-mail-unconfigured");
  r.check("страница не вернула 5xx при приглашении по почте", !page.failed.some((x) => /admin\/users|users/.test(x) && /^5/.test(x)), page.failed.join(" | "));

  // без почты: четыре сотрудника
  const pw = {};
  for (const u of STAFF) {
    await spaGoto(page, "/admin/org?invite=open&panel=open");
    await panel.getByRole("heading", { level: 3, name: "Пригласить сотрудника" }).waitFor();
    await panel.getByRole("radio", { name: "Временным паролем, без почты" }).check();
    await panel.getByLabel("Имя и фамилия").fill(u.name);
    await panel.getByLabel("Электронная почта").fill(u.email);
    await panel.getByLabel("Должность (необязательно)").fill(u.position);
    await panel.getByRole("checkbox", { name: u.role }).check();
    if (u.key === "director") {
      await panel.getByText(/Вы увидите временный пароль один раз/).waitFor();
      await shot(page, r, "invite-no-mail-form");
    }
    await panel.getByRole("button", { name: "Создать и показать пароль" }).click();
    const field = panel.getByLabel("Временный пароль", { exact: true });
    const ok = await step(page, r, `${u.key}: создан без почты, временный пароль показан`, async () => {
      await field.waitFor({ timeout: 30000 });
    });
    if (!ok) continue;
    pw[u.key] = { email: u.email, name: u.name, temp: await field.inputValue() };
    if (u.key === "director") {
      await shot(page, r, "invite-temp-password-shown", { mask: [field] });
      await panel.getByRole("button", { name: "Копировать" }).click();
      await step(page, r, "«Копировать»: пароль скопирован в буфер", async () => {
        await panel.getByText("Пароль скопирован").waitFor({ timeout: 5000 });
        const clip = await page.evaluate("navigator.clipboard.readText()");
        if (clip !== pw[u.key].temp) throw new Error("буфер не совпал");
      });
      await panel.getByText(/Пароль показан один раз/).waitFor().catch(() => {});
    }
    await panel.getByRole("button", { name: "Готово: пароль передан" }).click();
    await step(page, r, `${u.key}: после «Готово» пароля нет ни на экране, ни в адресе`, async () => {
      await panel.getByRole("heading", { level: 3, name: u.name }).waitFor({ timeout: 10000 });
      if ((await page.locator("body").innerText()).includes(pw[u.key].temp)) throw new Error("пароль на экране");
      if (page.url().includes(pw[u.key].temp)) throw new Error("пароль в адресе");
    });
  }
  saveState({ staff: { ...(state().staff ?? {}), ...pw } });

  // первый вход сотрудника: временный пароль -> обязательная смена
  await signOut(page);
  const d = state().staff.director;
  await login(page, d.email, "wrong-" + secret("x"));
  await step(page, r, "вход с неверным паролем — «Неверная почта или пароль»", async () => {
    await page.getByRole("alert").filter({ hasText: /Неверная почта или пароль/ }).waitFor({ timeout: 10000 });
  });
  await page.getByLabel("Пароль").fill(d.temp);
  await page.getByRole("button", { name: "Войти" }).click();
  await step(page, r, "вход с временным паролем ведёт на обязательную смену пароля", async () => {
    await page.waitForURL(/\/change-password$/, { timeout: 15000 });
  });
  await shot(page, r, "change-password-required");
  const own = secret("own");
  await page.getByLabel("Текущий пароль").fill(d.temp);
  await page.getByLabel("Новый пароль", { exact: true }).fill(own);
  await page.getByLabel("Повторите новый пароль").fill(own);
  await page.getByRole("button", { name: "Сменить пароль" }).click();
  await step(page, r, "пароль сменён, сотрудник попал в Платформу", async () => {
    await page.waitForURL((u) => !/change-password/.test(u.pathname), { timeout: 15000 });
    await page.getByRole("heading", { level: 1 }).first().waitFor();
  });
  saveState({ staff: { ...state().staff, director: { ...d, pw: own } } });
  r.note("ошибки консоли / 5xx", `${page.consoleErrors.join(" | ")} ;; ${page.failed.join(" | ")}`);
  r.save();
};


// ---------------------------------------------------------------------------------------------------------------------
// 3. Компания: реквизиты, логотип (CSP), бланк с предпросмотром, нумерация с предпросмотром, дефолты КП, статьи расхода,
// шаблоны, справочники, категории, платформенные настройки (НДС).
// Минимальный настоящий PNG 1x1 (файл уходит multipart-запросом через BFF в ERP).
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAMgAAAA8CAIAAACsOWLGAAAAt0lEQVR4nO3SQQkAIADAQB92tIrxLeEQ5OAC7LEx94LrxvMCvmQsEsYiYSwSxiJhLBLGImEsEsYiYSwSxiJhLBLGImEsEsYiYSwSxiJhLBLGImEsEsYiYSwSxiJhLBLGImEsEsYiYSwSxiJhLBLGImEsEsYiYSwSxiJhLBLGImEsEsYiYSwSxiJhLBLGImEsEsYiYSwSxiJhLBLGImEsEsYiYSwSxiJxAHN6pNs4sBMpAAAAAElFTkSuQmCC", "base64");
const TAB_TITLES = {
  details: "Реквизиты компании", brand: "Бланк и бренд документов", numbering: "Нумерация документов", quote: "Условия КП по умолчанию",
  charges: "Статьи расхода КП", templates: "Шаблоны документов и писем", reference: "Справочники ERP",
  categories: "Категории каталога и запросы на них", platform: "Платформенные настройки",
};
async function openCompany(page, tab) {
  await spaGoto(page, `/admin/company?tab=${tab}`);
  await page.getByRole("heading", { level: 1, name: "Компания" }).waitFor();
  await page.getByRole("heading", { level: 2, name: TAB_TITLES[tab] }).waitFor({ timeout: 20000 });
  await page.locator(".ant-skeleton").first().waitFor({ state: "detached", timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(500);
}
const RUN = String(Math.floor(Math.random() * 90) + 10); // уникальные значения: повторный прогон не упирается в «изменений нет»
const toast = (page, text) => page.locator(".ant-message").getByText(text);
/** Выбор в antd Select с поиском: фокус, ввод части названия, Enter. */
async function choose(page, select, text) {
  await select.focus();
  await page.keyboard.type(text);
  await page.waitForTimeout(400);
  await page.keyboard.press("Enter");
}

scenarios.s3 = async (browser) => {
  const r = new Report("s3");
  const { page } = await newPage(browser);
  const csp = [];
  page.on("console", (m) => { if (/Content Security Policy|Refused to/i.test(m.text())) csp.push(m.text().slice(0, 200)); });
  const st = state();
  await loginOk(page, st.adminEmail, st.adminPw);

  // --- реквизиты и логотип
  await openCompany(page, "details");
  await page.getByLabel("Телефон").fill(`+998 71 200 00 ${RUN}`);
  await page.getByLabel("Юридический адрес").fill("г. Ташкент, ул. Демонстрационная, 1");
  await page.getByRole("button", { name: "Сохранить реквизиты" }).click();
  await step(page, r, "реквизиты: сохранено", async () => { await toast(page, "Сохранено").waitFor({ timeout: 15000 }); });
  await toastsGone(page);
  await page.getByLabel("Выбрать файл: Логотип компании").setInputFiles({ name: "logo.png", mimeType: "image/png", buffer: PNG });
  await step(page, r, "логотип загружен и показан на экране (CSP не блокирует)", async () => {
    await page.getByRole("img", { name: "Логотип" }).waitFor({ timeout: 30000 });
    await page.waitForFunction(() => { const i = [...document.images].find((x) => x.alt.startsWith("Логотип")); return !!i && i.complete && i.naturalWidth > 0; }, null, { timeout: 15000 }).catch(() => { throw new Error("картинка не отрисована (naturalWidth=0)"); });
  });
  r.check("в консоли нет нарушений CSP при показе логотипа", csp.length === 0, csp.join(" | "));
  await toastsGone(page);
  await screen(page, r, "company-details-logo");
  await page.reload();
  await page.getByRole("heading", { level: 1, name: "Компания" }).waitFor();
  await step(page, r, "после перезагрузки реквизиты и логотип на месте", async () => {
    await page.getByRole("img", { name: "Логотип" }).waitFor({ timeout: 15000 });
    if ((await page.getByLabel("Телефон").inputValue()) !== `+998 71 200 00 ${RUN}`) throw new Error("телефон не сохранился");
  });

  // --- бланк и бренд с предпросмотром
  await openCompany(page, "brand");
  const frame = page.frameLocator('iframe[title="Образец: КП"]');
  await step(page, r, "бланк: образец документа показан (КП)", async () => { await frame.getByText("Коммерческое предложение", { exact: false }).waitFor({ timeout: 20000 }); });
  await page.getByLabel("Основной цвет", { exact: true }).fill("#047857");
  await step(page, r, "бланк: образец меняется до сохранения (цвет)", async () => {
    const f = page.locator('iframe[title="Образец: КП"]');
    for (let i = 0; i < 30; i++) {
      if ((await f.evaluate((e) => e.srcdoc ?? "")).includes("--accent: #047857")) return;
      await page.waitForTimeout(500);
    }
    throw new Error("в образце нет нового цвета");
  });
  await page.locator(".ant-segmented-item-label", { hasText: "Договор" }).click();
  await step(page, r, "бланк: образец «Договор» переключается", async () => { await page.frameLocator('iframe[title="Образец: Договор"]').getByText("Договор", { exact: false }).first().waitFor({ timeout: 45000 }); });
  await page.locator(".ant-segmented-item-label", { hasText: "КП" }).first().click();
  await page.getByLabel("Подписант", { exact: true }).fill(`Демо Подписантов ${RUN}`);
  await page.getByRole("button", { name: "Сохранить бланк" }).click();
  await step(page, r, "бланк: сохранён", async () => { await toast(page, "Сохранено").waitFor({ timeout: 15000 }); });
  await toastsGone(page);
  await page.locator('iframe[title^="Образец"]').first().scrollIntoViewIfNeeded();
  await screen(page, r, "company-brand", { exclude: ["iframe.pf-co-frame"] });

  // --- нумерация с предпросмотром
  await openCompany(page, "numbering");
  const samples = page.getByRole("list", { name: "Образец номеров" });
  await page.getByLabel("Префикс нумерации").fill(`DEMO${RUN}`);
  await step(page, r, "нумерация: образец номеров по черновику (префикс DEMO)", async () => { await samples.getByText(new RegExp(`DEMO${RUN}-КП-\\d{4}-00001`)).waitFor({ timeout: 15000 }); });
  await page.getByLabel("Маска номера").fill("{type}-").catch(() => {});
  await step(page, r, "нумерация: маска без {seq} — ошибка словами, сохранение закрыто", async () => {
    await page.getByText("В маске обязателен токен {seq}").waitFor({ timeout: 5000 });
  });
  await page.getByLabel("Маска номера").fill("{prefix}{type}-{YYYY}-{seq}");
  await page.getByRole("button", { name: "Сохранить нумерацию" }).click();
  await step(page, r, "нумерация: сохранена", async () => { await toast(page, "Нумерация сохранена").waitFor({ timeout: 15000 }); });
  await toastsGone(page);
  await screen(page, r, "company-numbering");

  // --- условия КП (НДС, срок)
  await openCompany(page, "quote");
  await page.getByLabel("Срок действия КП, дней").fill(RUN);
  await page.getByLabel("Ставка НДС, %").first().fill("12");
  await page.getByRole("button", { name: "Сохранить условия" }).click();
  await step(page, r, "условия КП: сохранены", async () => { await toast(page, "Сохранено").waitFor({ timeout: 15000 }); });
  r.note("администратор без роли «себестоимость/маржа»: поля маржи", (await page.getByText(/Поля маржи скрыты/).isVisible().catch(() => false)) ? "скрыты, сказано словами" : "видны");
  await toastsGone(page);
  await screen(page, r, "company-quote");

  // --- статьи расхода: добавить, изменить, удалить
  await openCompany(page, "charges");
  await page.getByRole("button", { name: "Добавить статью" }).click();
  const dlg = page.getByRole("dialog", { name: "Новая статья расхода" });
  await dlg.waitFor();
  await choose(page, dlg.getByLabel("Базис поставки"), "DAP");
  await choose(page, dlg.getByLabel("Статья", { exact: true }), "Фрахт");
  await dlg.getByLabel("Сумма").fill("250");
  await shot(page, r, "company-charges-add");
  await dlg.getByRole("button", { name: "Сохранить" }).click();
  await step(page, r, "статья расхода: добавлена", async () => { await toast(page, "Сохранено").waitFor({ timeout: 15000 }); });
  await toastsGone(page);
  const row = page.getByRole("row").filter({ hasText: "250" });
  await step(page, r, "статья расхода: строка в таблице", async () => { await row.first().waitFor({ timeout: 10000 }); });
  await screen(page, r, "company-charges");
  const editBtn = page.getByRole("button", { name: /^Изменить:/ }).first();
  await editBtn.click();
  const edit = page.getByRole("dialog", { name: "Изменить статью расхода" });
  await edit.getByLabel("Сумма").fill("300");
  await edit.getByRole("button", { name: "Сохранить" }).click();
  await step(page, r, "статья расхода: изменена (300)", async () => { await page.getByRole("row").filter({ hasText: "300" }).first().waitFor({ timeout: 10000 }); });
  await page.getByRole("button", { name: /^Удалить:/ }).first().click();
  const del = page.getByRole("dialog", { name: /Удалить статью/ });
  await step(page, r, "статья расхода: удаление с «Что произойдёт»", async () => { await del.getByText("Что произойдёт").waitFor(); });
  await del.getByRole("button", { name: "Удалить" }).click();
  await step(page, r, "статья расхода: удалена", async () => { await page.getByText("Статей расхода пока нет").waitFor({ timeout: 10000 }); });

  // --- шаблоны документов и писем
  await openCompany(page, "templates");
  // уборка копий прошлых прогонов («Свой»): гейт идемпотентен
  for (let i = 0; i < 6; i++) {
    const own = page.getByRole("row").filter({ hasText: "Свой" }).first();
    if (!(await own.isVisible().catch(() => false))) break;
    await own.getByRole("button", { name: /^Удалить:/ }).click();
    await page.getByRole("dialog", { name: /Удалить шаблон/ }).getByRole("button", { name: "Удалить" }).click();
    await toast(page, "Шаблон удалён").waitFor({ timeout: 15000 }).catch(() => {});
    await toastsGone(page);
  }
  const wantedName = `Договор поставки (рельсы ${RUN})`;
  await page.getByRole("button", { name: /^Скопировать к себе: Договор поставки/ }).click();
  const copy = page.getByRole("dialog", { name: /Скопировать/ });
  await copy.getByLabel("Название").fill(wantedName);
  await copy.getByRole("button", { name: "Скопировать к себе" }).click();
  await step(page, r, "шаблон документа: копия образца создана", async () => { await toast(page, "Копия создана").waitFor({ timeout: 15000 }); });
  await toastsGone(page);
  await page.waitForTimeout(1500);
  const named = await page.getByRole("row").filter({ hasText: wantedName }).count();
  r.check("шаблон документа: копия получила введённое администратором название", named === 1, named === 1 ? "" : `строки с «${wantedName}» нет; свои шаблоны: ${(await page.getByRole("row").filter({ hasText: "Свой" }).allInnerTexts()).map((x) => x.split("\t")[0]).join(" ; ")}`);
  const ownRow = page.getByRole("row").filter({ hasText: "Свой" }).first();
  await ownRow.getByRole("button", { name: /^Изменить:/ }).click();
  const editor = page.getByRole("dialog", { name: "Изменить шаблон документа" });
  const body = editor.getByLabel(/^Текст шаблона/);
  await body.fill("<p>{{buyer_name}} {{mystery}}</p>");
  await page.waitForTimeout(2500);
  await shot(page, r, "company-templates-editor-unknown-placeholder");
  await editor.getByRole("button", { name: "Сохранить" }).click();
  await page.waitForTimeout(3000);
  const edAlert = (await editor.getByRole("alert").first().innerText().catch(() => "")).replace(/\n+/g, " | ");
  r.check("шаблон договора с неполным телом: ответ называет, каких блоков не хватает", /блок|таблиц|итог|подпис/i.test(edAlert), `текст ответа администратору: «${edAlert || "сохранено без ошибки"}»`);
  await shot(page, r, "company-templates-editor-save-error");
  await editor.getByRole("button", { name: "Отмена" }).click();
  await ownRow.getByRole("button", { name: /^Изменить:/ }).click();
  await editor.getByLabel("Название").fill(wantedName);
  await editor.getByRole("button", { name: "Сохранить" }).click();
  await step(page, r, "шаблон документа: правка названия сохранена (тело нетронуто)", async () => { await toast(page, "Сохранено").waitFor({ timeout: 15000 }); });
  await step(page, r, "шаблон документа: в списке название, введённое при правке", async () => { await page.getByRole("row").filter({ hasText: wantedName }).first().waitFor({ timeout: 10000 }); });
  await toastsGone(page);
  await page.getByRole("row").filter({ hasText: "Свой" }).first().getByRole("button", { name: /^Удалить:/ }).click();
  await page.getByRole("dialog", { name: /Удалить шаблон/ }).getByRole("button", { name: "Удалить" }).click();
  await step(page, r, "шаблон документа: удалён", async () => { await toast(page, "Шаблон удалён").waitFor({ timeout: 15000 }); });
  await toastsGone(page);
  await page.locator(".ant-segmented-item-label", { hasText: "Шаблоны писем" }).click();
  await page.waitForTimeout(1200);
  await page.getByRole("button", { name: "Создать шаблон письма" }).click();
  const em = page.getByRole("dialog", { name: "Новый шаблон письма" });
  await em.getByLabel("Ключ письма").fill("act_issued");
  await em.getByLabel("Тема").fill("Акт {{number}}");
  await em.getByLabel("Текст письма", { exact: true }).fill("Акт выпущен.");
  await em.getByRole("button", { name: "Сохранить" }).click();
  await step(page, r, "шаблон письма: создан", async () => { await page.getByRole("row", { name: /act_issued/ }).waitFor({ timeout: 15000 }); });
  await screen(page, r, "company-templates-emails");
  await page.getByRole("button", { name: "Удалить: act_issued" }).click();
  await page.getByRole("dialog", { name: /Удалить шаблон/ }).getByRole("button", { name: "Удалить" }).click();
  await step(page, r, "шаблон письма: удалён", async () => { await page.getByRole("row", { name: /act_issued/ }).waitFor({ state: "detached", timeout: 15000 }); });

  // --- справочники
  await openCompany(page, "reference");
  await page.getByRole("button", { name: "Добавить строку" }).click();
  const ref = page.getByRole("dialog", { name: "Новая строка справочника" });
  await ref.getByLabel("Код", { exact: true }).fill("ZZ");
  await ref.getByLabel("Название").fill("Демо-страна");
  await ref.getByRole("button", { name: "Сохранить" }).click();
  await step(page, r, "справочник «Страны»: строка добавлена", async () => { await page.getByRole("row", { name: /Демо-страна/ }).waitFor({ timeout: 15000 }); });
  await page.getByRole("button", { name: "Удалить: Демо-страна" }).click();
  await page.getByRole("dialog", { name: /Удалить/ }).getByRole("button", { name: "Удалить" }).click();
  await step(page, r, "справочник «Страны»: неиспользуемая строка удалена", async () => { await page.getByRole("row", { name: /Демо-страна/ }).waitFor({ state: "detached", timeout: 15000 }); });
  await page.locator(".ant-segmented-item-label", { hasText: "Валюты" }).click();
  await page.waitForTimeout(1500);
  const cur = page.getByRole("button", { name: /^Отключить:/ }).first();
  const curLabel = await cur.getAttribute("aria-label");
  await cur.click();
  await step(page, r, "справочник «Валюты»: строка отключена", async () => { await page.getByRole("button", { name: curLabel.replace("Отключить", "Включить") }).waitFor({ timeout: 15000 }); });
  await page.getByRole("button", { name: curLabel.replace("Отключить", "Включить") }).click();
  await step(page, r, "справочник «Валюты»: строка включена обратно", async () => { await page.getByRole("button", { name: curLabel }).waitFor({ timeout: 15000 }); });
  await page.locator(".ant-segmented-item-label", { hasText: "Единицы" }).click();
  await page.waitForTimeout(1000);
  await page.locator(".ant-segmented-item-label", { hasText: "Базисы поставки" }).click();
  await page.waitForTimeout(1000);
  await screen(page, r, "company-reference");

  // --- категории каталога
  await openCompany(page, "categories");
  await page.getByRole("button", { name: /^Подкатегория: добавить в/ }).first().click();
  const cat = page.getByRole("dialog", { name: "Новая категория" });
  await cat.getByLabel("Название").fill("Демо-кабели");
  await cat.getByRole("button", { name: "Сохранить" }).click();
  await step(page, r, "категория: подкатегория добавлена", async () => { await page.getByText("Демо-кабели", { exact: true }).waitFor({ timeout: 15000 }); });
  await page.getByRole("button", { name: "Изменить: Демо-кабели" }).click();
  const rn = page.getByRole("dialog", { name: "Изменить категорию" });
  await rn.getByLabel("Название").fill("Демо-силовые кабели");
  await rn.getByRole("button", { name: "Сохранить" }).click();
  await step(page, r, "категория: переименована", async () => { await page.getByText("Демо-силовые кабели", { exact: true }).waitFor({ timeout: 15000 }); });
  await screen(page, r, "company-categories");
  await page.getByRole("button", { name: "Удалить: Демо-силовые кабели" }).click();
  await page.getByRole("dialog", { name: /Удалить категорию/ }).getByRole("button", { name: "Удалить" }).click();
  await step(page, r, "категория: удалена", async () => { await page.getByText("Демо-силовые кабели", { exact: true }).waitFor({ state: "detached", timeout: 15000 }); });

  // --- платформенные настройки (НДС)
  await openCompany(page, "platform");
  const vat = page.getByLabel("Ставка НДС, %");
  r.note("НДС до правки", await vat.inputValue());
  await vat.fill(String((Number(RUN) % 50) + 1));
  await page.getByRole("button", { name: "Сохранить ставку НДС" }).click();
  await step(page, r, "платформенные настройки: ставка НДС сохранена", async () => { await toast(page, "Сохранено").first().waitFor({ timeout: 15000 }); });
  await toastsGone(page);
  await page.reload();
  await page.getByRole("heading", { level: 2, name: TAB_TITLES.platform }).waitFor({ timeout: 20000 });
  await page.waitForTimeout(1500);
  { const got = await page.getByLabel("Ставка НДС, %").inputValue(); r.check("НДС после перезагрузки = введённому", Number(got) === (Number(RUN) % 50) + 1, `введено ${(Number(RUN) % 50) + 1}, на экране ${got}`); }
  await screen(page, r, "company-platform");
  r.note("ошибки консоли / 5xx", `${page.consoleErrors.join(" | ")} ;; ${page.failed.join(" | ")}`);
  r.save();
};


// 3b. Категории: запрос создал сотрудник (ERP API от имени директора — экрана подачи в Платформе нет, это не административная функция);
// администратор решает его в Платформе: отклонить с причиной; завести категорию и одобрить с выбором категории.
scenarios.s3b = async (browser) => {
  const r = new Report("s3b");
  const { page } = await newPage(browser);
  const st = state();
  await loginOk(page, st.adminEmail, st.adminPw);
  await openCompany(page, "categories");
  await page.locator(".ant-segmented-item-label", { hasText: /^Запросы/ }).click();
  await page.waitForTimeout(1500);
  const label = await page.locator(".ant-segmented-item-label", { hasText: /^Запросы/ }).innerText();
  r.check("в «Запросах» ожидают решения два запроса сотрудника", /\(2\)/.test(label), label);
  await step(page, r, "запрос виден строкой со статусом «На рассмотрении»", async () => { await page.getByRole("row", { name: /Тормозные колодки/ }).getByText("На рассмотрении").waitFor({ timeout: 10000 }); });
  await screen(page, r, "company-category-requests");

  await page.getByRole("button", { name: "Отклонить запрос: Демо: Тормозные колодки" }).click();
  const reject = page.getByRole("dialog", { name: /Отклонить запрос/ });
  await step(page, r, "отклонение: «Что произойдёт» и обязательная причина", async () => {
    await reject.getByText("Что произойдёт").waitFor();
    await reject.getByText("Причина обязательна").waitFor();
  });
  await reject.getByLabel("Причина отказа").fill("Дубль существующей категории");
  await shot(page, r, "company-category-reject");
  await reject.getByRole("button", { name: "Отклонить" }).click();
  await step(page, r, "запрос отклонён, причина в строке", async () => {
    await toast(page, "Запрос отклонён").waitFor({ timeout: 15000 });
    const row = page.getByRole("row", { name: /Тормозные колодки/ });
    await row.getByText("Отклонён").waitFor({ timeout: 10000 });
    await row.getByText("Дубль существующей категории").waitFor({ timeout: 10000 });
  });
  await toastsGone(page);

  // категорию, о которой просили, администратор заводит сам; затем одобряет запрос с выбором этой категории
  await page.locator(".ant-segmented-item-label", { hasText: "Категории" }).first().click();
  await page.getByRole("button", { name: "Добавить категорию" }).click();
  const cat = page.getByRole("dialog", { name: "Новая категория" });
  await cat.getByLabel("Название").fill("Демо-стрелочные переводы");
  await cat.getByRole("button", { name: "Сохранить" }).click();
  await step(page, r, "категория, о которой просили, заведена администратором", async () => { await page.getByText("Демо-стрелочные переводы", { exact: true }).waitFor({ timeout: 15000 }); });
  await page.locator(".ant-segmented-item-label", { hasText: /^Запросы/ }).click();
  await page.waitForTimeout(1500);
  await page.getByRole("button", { name: "Одобрить запрос: Демо: Стрелочные переводы" }).click();
  const approve = page.getByRole("dialog", { name: /Одобрить запрос/ });
  await step(page, r, "одобрение: сказано, что сама категория этим действием не создаётся", async () => { await approve.getByText(/Сама категория в каталоге этим действием не создаётся/).waitFor(); });
  await choose(page, approve.getByLabel("Категория, которую вы завели для запроса"), "Демо-стрелочные");
  await shot(page, r, "company-category-approve");
  await approve.getByRole("button", { name: "Одобрить" }).click();
  await step(page, r, "запрос одобрен, статус в строке", async () => {
    await toast(page, "Запрос одобрен").waitFor({ timeout: 15000 });
    await page.getByRole("row", { name: /Стрелочные переводы/ }).getByText("Одобрен").waitFor({ timeout: 10000 });
  });
  await toastsGone(page);
  await screen(page, r, "company-category-requests-decided");
  // убираем заведённую категорию (уборка)
  await page.locator(".ant-segmented-item-label", { hasText: "Категории" }).first().click();
  await page.waitForTimeout(1000);
  r.note("ошибки консоли / 5xx", `${page.consoleErrors.join(" | ")} ;; ${page.failed.join(" | ")}`);
  r.save();
};


// ---------------------------------------------------------------------------------------------------------------------
// 5b. Сброс пароля (по почте — ошибка при ненастроенной почте; временным паролем — один раз), вход сотрудника с новым временным
// паролем, роли (создать роль, вкладка «Журнал»), журнал аудита с фильтрами, профиль и тестовое уведомление.
async function openOrgCard(page, name) {
  await spaGoto(page, "/admin/org");
  await page.getByRole("link", { name: `Открыть карточку: ${name}` }).click();
  await side(page).getByRole("heading", { level: 3, name }).waitFor({ timeout: 15000 });
}

scenarios.s5b = async (browser) => {
  const r = new Report("s5b");
  const { page, ctx } = await newPage(browser);
  await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: new URL(process.env.QA_BASE ?? "http://platform.localhost:8097").origin });
  const st = state();
  await loginOk(page, st.adminEmail, st.adminPw);
  const panel = side(page);

  // --- сброс по почте: почта не настроена
  await openOrgCard(page, "Демо Менеджеров");
  await panel.getByRole("button", { name: "Сбросить пароль" }).click();
  const reset = panel.getByRole("group", { name: "Сброс пароля" });
  await step(page, r, "сброс пароля: «Что произойдёт», варианты «По почте» / «Временным паролем»", async () => {
    await reset.getByText("Что произойдёт").waitFor();
    await reset.getByRole("radio", { name: "Временным паролем" }).waitFor();
  });
  await shot(page, r, "org-reset-password");
  await panel.getByRole("button", { name: "Сбросить и отправить письмо" }).click();
  await step(page, r, "сброс по почте без SMTP — понятная ошибка", async () => { await panel.getByRole("alert").first().waitFor({ timeout: 15000 }); });
  const mailErr = (await panel.getByRole("alert").first().innerText()).replace(/\n+/g, " | ");
  r.note("текст ошибки сброса по почте", mailErr);
  r.check("сброс по почте без SMTP не оставил сотрудника без пароля молча (текст ошибки не пуст, нет 5xx)", mailErr.length > 10 && !page.failed.some((x) => /^5/.test(x) && /password/.test(x)), page.failed.join(" | "));
  await shot(page, r, "org-reset-mail-error");

  // --- временным паролем, показан один раз
  await reset.getByRole("radio", { name: "Временным паролем" }).check();
  await panel.getByRole("button", { name: "Выдать пароль" }).click();
  const tmpField = panel.getByRole("textbox", { name: "Временный пароль" });
  await step(page, r, "сброс временным паролем: пароль показан", async () => { await tmpField.waitFor({ timeout: 20000 }); });
  const tmp = await tmpField.inputValue();
  await shot(page, r, "org-temporary-password", { mask: [tmpField] });
  await panel.getByRole("button", { name: "Копировать" }).click().catch(() => {});
  await panel.getByRole("button", { name: "Готово: пароль передан" }).click();
  await step(page, r, "после «Готово» временного пароля на экране нет", async () => {
    if ((await page.locator("body").innerText()).includes(tmp)) throw new Error("пароль остался на экране");
  });
  saveState({ staff: { ...state().staff, manager: { ...state().staff.manager, temp: tmp } } });

  // --- вход сотрудника с новым временным паролем -> обязательная смена
  await signOut(page);
  await login(page, state().staff.manager.email, tmp);
  await step(page, r, "вход со сброшенным временным паролем ведёт на обязательную смену", async () => { await page.waitForURL(/\/change-password$/, { timeout: 15000 }); });
  const own = secret("own");
  await page.getByLabel("Текущий пароль").fill(tmp);
  await page.getByLabel("Новый пароль", { exact: true }).fill(own);
  await page.getByLabel("Повторите новый пароль").fill(own);
  await page.getByRole("button", { name: "Сменить пароль" }).click();
  await step(page, r, "сотрудник сменил пароль и вошёл", async () => { await page.waitForURL((u) => !/change-password/.test(u.pathname), { timeout: 15000 }); await page.getByRole("heading", { level: 1 }).first().waitFor(); });
  saveState({ staff: { ...state().staff, manager: { ...state().staff.manager, pw: own } } });
  await signOut(page);
  await loginOk(page, st.adminEmail, st.adminPw);

  // --- роли: создать роль, переименовать, вкладка «Журнал»
  await spaGoto(page, "/admin/roles");
  await page.getByRole("heading", { level: 1, name: "Ролевая матрица" }).waitFor();
  await page.getByRole("button", { name: /^Менеджер/ }).first().waitFor({ timeout: 15000 });
  await screen(page, r, "roles-matrix");
  const roleName = `Демо Складчик ${RUN}`;
  await page.getByRole("button", { name: "Создать роль" }).click();
  await panel.getByRole("heading", { level: 3, name: "Новая роль" }).waitFor();
  await panel.getByLabel("Название").fill(roleName);
  const leads = page.locator("table.pf-matrix").getByRole("combobox", { name: new RegExp(`Все сообщения, Все лиды.*роль «${roleName}»`) });
  await leads.selectOption({ label: "Только чтение" });
  await panel.getByRole("button", { name: "Создать роль" }).click();
  await step(page, r, "роль создана", async () => { await page.getByText(`Роль «${roleName}» создана`).waitFor({ timeout: 15000 }); });
  await toastsGone(page);
  await panel.getByLabel("Название").fill(roleName + " (склад)");
  await panel.getByRole("button", { name: "Сохранить роль" }).click();
  await step(page, r, "роль сохранена после правки названия", async () => { await page.getByText("Роль сохранена").waitFor({ timeout: 15000 }); });
  await panel.getByRole("tab", { name: "Журнал" }).click();
  await step(page, r, "вкладка «Журнал» роли: кто, когда, что изменилось", async () => {
    await panel.getByRole("heading", { level: 3, name: new RegExp("Журнал роли") }).waitFor({ timeout: 15000 });
    await panel.getByText(/Название: «/).waitFor({ timeout: 10000 });
    await panel.getByText(/Демо Админов/).first().waitFor({ timeout: 5000 });
  });
  await screen(page, r, "roles-journal-tab");

  // --- журнал аудита с фильтрами
  await spaGoto(page, "/admin/audit");
  await page.getByRole("heading", { level: 1, name: "Журнал аудита" }).waitFor();
  const table = page.getByRole("table", { name: "Записи журнала аудита" });
  await step(page, r, "журнал аудита: записи за гейт (кто, что, когда, над чем)", async () => { await table.getByRole("row").nth(5).waitFor({ timeout: 15000 }); });
  const total0 = (await page.getByText(/^Записей: \d+/).first().innerText().catch(() => "")) || `строк в таблице ${await table.getByRole("row").count()}`;
  r.note("журнал аудита: счётчик до фильтров", total0);
  await screen(page, r, "audit-list");
  const sw = page.getByRole("switch", { name: "Показывать входы в систему" });
  await sw.click();
  await page.waitForTimeout(1500);
  const totalLogins = (await page.getByText(/^Записей: \d+/).first().innerText().catch(() => ""));
  r.check("фильтр «Показывать входы в систему» меняет выдачу", totalLogins !== total0, `${total0} -> ${totalLogins}`);
  await sw.click();
  await page.waitForTimeout(800);
  await page.getByLabel("Объект").click();
  await page.waitForTimeout(500);
  const objectOptions = await page.locator(".ant-select-item-option").allInnerTexts();
  r.note("фильтр «Объект»: варианты", objectOptions.join(" | "));
  const pick = page.locator(".ant-select-item-option").filter({ hasText: /Роль Платформы/ }).first();
  if (await pick.isVisible().catch(() => false)) await pick.click(); else await page.keyboard.press("Escape");
  await page.waitForTimeout(1500);
  const rowsRole = await table.getByRole("row").count();
  r.check("фильтр «Объект = Роль Платформы» оставляет только записи ролей", rowsRole >= 2 && (await table.getByRole("row").allInnerTexts()).slice(1).every((x) => /Роль/.test(x)), `строк ${rowsRole}`);
  await shot(page, r, "audit-filter-role");
  await page.getByLabel("С даты").fill("2026-12-01");
  await step(page, r, "фильтр «С даты» в будущем — «По этим фильтрам записей нет»", async () => { await page.getByText("По этим фильтрам записей нет").waitFor({ timeout: 10000 }); });
  await page.getByRole("button", { name: "Сбросить фильтры" }).first().click();
  await page.waitForTimeout(1200);
  await page.getByRole("link", { name: /^Открыть запись: Сбросил пароль/ }).first().click();
  await step(page, r, "запись аудита открывается в боковом окне: что именно изменилось, без секретов", async () => {
    await panel.getByRole("heading", { level: 3 }).first().waitFor({ timeout: 10000 });
    const txt = await panel.innerText();
    if (txt.includes(tmp)) throw new Error("временный пароль в журнале!");
  });
  await screen(page, r, "audit-entry-panel");

  // --- профиль и тестовое уведомление
  await spaGoto(page, "/dashboard/queue");
  await openAvatarMenu(page);
  await page.getByRole("menuitem", { name: "Профиль", exact: true }).click();
  const dlg = page.getByRole("dialog", { name: "Профиль" });
  await step(page, r, "профиль: имя, почта, роли, доступ, подписки на уведомления", async () => { await dlg.getByText("Уведомления").waitFor({ timeout: 10000 }); });
  await shot(page, r, "profile-dialog");
  const testBtn = dlg.getByRole("button", { name: "Тестовое уведомление" });
  const disabled = await testBtn.isDisabled();
  r.note("профиль: «Тестовое уведомление» (Telegram не привязан)", disabled ? "кнопка недоступна, причина на экране: Telegram не привязан" : "кнопка доступна");
  if (!disabled) {
    await testBtn.click();
    await page.waitForTimeout(4000);
    r.note("результат тестового уведомления", (await dlg.innerText()).replace(/\n+/g, " | ").slice(-300));
  }
  const toggle = dlg.getByRole("switch").first();
  if (await toggle.isVisible().catch(() => false)) {
    if (await toggle.isDisabled()) {
      r.note("профиль: подписки на уведомления недоступны, пока Telegram не привязан", "переключатели неактивны, причина написана на экране (Telegram: Не привязан)");
    } else {
      const before = await toggle.getAttribute("aria-checked");
      await toggle.click();
      await page.waitForTimeout(2000);
      r.check("профиль: подписка на уведомления переключается и не падает", (await toggle.getAttribute("aria-checked")) !== before || (await dlg.getByRole("alert").count()) > 0, `было ${before}, стало ${await toggle.getAttribute("aria-checked")}`);
    }
  }
  await screen(page, r, "profile-dialog-axe", { narrow: true });
  r.note("ошибки консоли / 5xx", `${page.consoleErrors.join(" | ")} ;; ${page.failed.join(" | ")}`);
  r.save();
};


// ---------------------------------------------------------------------------------------------------------------------
// 6. CRM · База знаний и Admin · Настройки бота.
async function openKb(page, query = "") {
  await spaGoto(page, `/crm/kb${query}`);
  await page.getByRole("heading", { level: 1, name: "База знаний" }).waitFor();
  await page.waitForTimeout(1500);
  await page.locator(".ant-skeleton").first().waitFor({ state: "detached", timeout: 15000 }).catch(() => {});
}
const botNav = (page) => page.getByRole("navigation", { name: "Разделы настроек бота" });
async function openBot(page, section) {
  await spaGoto(page, "/admin/bot");
  await page.getByRole("heading", { level: 1, name: "Настройки бота" }).waitFor();
  await page.waitForTimeout(1200);
  if (section) {
    await botNav(page).getByRole("link", { name: section, exact: true }).click();
    await page.getByRole("heading", { level: 2, name: section }).waitFor({ timeout: 15000 });
  }
  await page.locator(".ant-skeleton").first().waitFor({ state: "detached", timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(500);
}

scenarios.s6kb = async (browser) => {
  const r = new Report("s6kb");
  const { page } = await newPage(browser);
  const st = state();
  await loginOk(page, st.adminEmail, st.adminPw);
  const panel = side(page);

  await openKb(page);
  if (await page.getByText("Документов пока нет").isVisible().catch(() => false)) await screen(page, r, "kb-empty"); // пустое состояние только на чистом стенде

  // загрузка файла: ошибка формата, затем верный файл
  await page.getByRole("link", { name: "Загрузить файл" }).first().click();
  const form = panel.getByRole("form", { name: "Загрузить файл Markdown" });
  await step(page, r, "загрузка: форма с «Что произойдёт», кнопка недоступна без файла", async () => {
    await form.getByRole("group", { name: "Что произойдёт" }).waitFor();
    if (!(await form.getByRole("button", { name: "Загрузить документ" }).isDisabled())) throw new Error("кнопка доступна без файла");
  });
  await form.getByLabel("Файл .md").setInputFiles({ name: "price.pdf", mimeType: "application/pdf", buffer: Buffer.from("x") });
  await step(page, r, "загрузка PDF — «Принимаются только файлы Markdown (.md)»", async () => { await form.getByRole("alert").filter({ hasText: /только файлы Markdown/ }).waitFor({ timeout: 5000 }); });
  await form.getByLabel("Файл .md").setInputFiles({ name: "bad.md", mimeType: "text/markdown", buffer: Buffer.from("# Без front matter\n") });
  await form.getByRole("button", { name: "Загрузить документ" }).click();
  await step(page, r, "загрузка .md без front matter — ошибка словами от CRM", async () => { await form.getByRole("alert").filter({ hasText: /front matter/ }).waitFor({ timeout: 10000 }); });
  await shot(page, r, "kb-upload-format-error");
  const doc = (title) => `---\ntitle: ${title}\nlanguage: ru\nsource: Договор\nupdated: 2026-10-26\n---\n# ${title}\n\nСрок поставки рельсов — от 14 рабочих дней с момента предоплаты. Гарантия на продукцию — 24 месяца.\n`;
  await form.getByLabel("Файл .md").setInputFiles({ name: "terms.md", mimeType: "text/markdown", buffer: Buffer.from(doc(`Сроки и условия поставки ${RUN}`)) });
  await form.getByLabel("Название").fill(`Сроки и условия поставки ${RUN}`); // название из имени отвергнутого файла (price.pdf) остаётся в поле — см. отчёт
  await form.getByRole("button", { name: "Загрузить документ" }).click();
  await step(page, r, "верный .md принят: «Документ добавлен — индексация займёт до минуты»", async () => { await page.getByText(/Документ добавлен/).first().waitFor({ timeout: 20000 }); });
  await toastsGone(page);

  // ручной ввод
  await page.getByRole("link", { name: "Добавить вручную" }).first().click();
  const manual = panel.getByRole("form", { name: "Добавить документ вручную" });
  await manual.getByLabel("Название").fill(`Рассрочка платежа ${RUN}`);
  await manual.getByLabel("Текст документа (Markdown)").fill("Оплата частями возможна по договору: 50 % предоплата, остаток — после поставки.");
  await manual.getByRole("button", { name: "Добавить документ" }).click();
  await step(page, r, "ручной ввод: документ добавлен", async () => { await page.getByRole("link", { name: `Открыть документ: Рассрочка платежа ${RUN}` }).waitFor({ timeout: 20000 }); });

  // статус индексации словом (без ключей эмбеддингов/docling индексация может не пройти)
  await page.waitForTimeout(25000);
  await openKb(page);
  const rows = (await page.locator("table tbody tr").allInnerTexts()).map((x) => x.replace(/\s+/g, " ").trim());
  r.note("документы и статусы индексации через ~30 с", rows.join(" ;; "));
  const states = ["Готов", "В очереди", "Обрабатывается", "Ошибка"].filter((w) => rows.some((x) => x.includes(w)));
  r.check("у каждого документа статус индексации словом", rows.length >= 2 && rows.every((x) => /Готов|В очереди|Обрабатывается|Ошибка|Выключен/.test(x)), states.join(", "));
  await screen(page, r, "kb-documents");

  // карточка документа, «Переиндексировать»
  await page.getByRole("link", { name: `Открыть документ: Сроки и условия поставки ${RUN}` }).click();
  await panel.getByRole("heading", { level: 3, name: `Сроки и условия поставки ${RUN}` }).waitFor({ timeout: 15000 });
  r.note("карточка документа", (await panel.innerText()).replace(/\n+/g, " | ").slice(0, 600));
  await screen(page, r, "kb-document-card");
  await panel.getByRole("button", { name: "Переиндексировать" }).click();
  const again = panel.getByRole("form", { name: "Переиндексировать" });
  await step(page, r, "переиндексация: «Что произойдёт»", async () => { await again.getByRole("group", { name: "Что произойдёт" }).waitFor(); });
  await again.getByRole("button", { name: "Переиндексировать документ" }).click();
  await page.waitForTimeout(2500);
  r.note("после «Переиндексировать»", (await page.locator("table tbody tr").allInnerTexts()).map((x) => x.replace(/\s+/g, " ")).join(" ;; "));

  // «Что найдёт бот» (поиск)
  await openKb(page);
  await page.getByLabel("Вопрос клиента").fill("Какие сроки поставки рельсов?");
  await page.getByRole("button", { name: "Найти" }).click();
  await page.waitForTimeout(6000);
  const found = (await page.locator("main").innerText()).replace(/\n+/g, " | ");
  r.note("«Что найдёт бот»: ответ поиска", found.slice(found.indexOf("Что найдёт бот"), found.indexOf("Что найдёт бот") + 700));
  await shot(page, r, "kb-search");

  // пробелы
  await openKb(page, "?view=gaps");
  await step(page, r, "пробелы: экран и пустое состояние словами", async () => { await page.getByRole("heading", { level: 2, name: "Пробелы базы знаний" }).waitFor(); });
  await screen(page, r, "kb-gaps");

  // песочница
  await openKb(page, "?view=sandbox");
  await page.getByLabel("Вопрос клиента").fill("Какие сроки поставки рельсов?");
  await page.getByRole("button", { name: "Отправить боту" }).click();
  await page.waitForTimeout(12000);
  const sb = (await page.locator("main").innerText()).replace(/\n+/g, " | ");
  r.note("песочница: ответ без ключей моделей", sb.slice(sb.indexOf("Вопрос клиента"), sb.indexOf("Вопрос клиента") + 600));
  r.check("песочница: без ключей модели — ожидаемая ошибка словами, не белый экран", /не отвечает|не может|ошибк|Повторите|недоступ|ключ/i.test(sb) || (await page.getByRole("log").count()) > 0, "");
  await shot(page, r, "kb-sandbox-no-key");
  await page.getByRole("button", { name: "Начать заново" }).click().catch(() => {});
  await screen(page, r, "kb-sandbox");
  r.note("ошибки консоли / 5xx", `${page.consoleErrors.join(" | ")} ;; ${page.failed.join(" | ")}`);
  r.save();
};

scenarios.s6bot = async (browser) => {
  const r = new Report("s6bot");
  const { page } = await newPage(browser);
  const st = state();
  await loginOk(page, st.adminEmail, st.adminPw);
  await openBot(page, "Компания");
  await step(page, r, "настройки бота: 16 разделов в навигации по группам", async () => { if ((await botNav(page).getByRole("link").count()) !== 16) throw new Error(String(await botNav(page).getByRole("link").count())); });
  await page.getByLabel("Телефон компании (бот называет его по просьбе клиента)").fill(`+998 71 100 00 ${RUN}`);
  await step(page, r, "«Есть несохранённые изменения» + «Отменить изменения»", async () => {
    await page.getByText("Есть несохранённые изменения").waitFor({ timeout: 5000 });
  });
  await page.getByRole("button", { name: "Отменить изменения" }).click();
  await page.getByLabel("Телефон компании (бот называет его по просьбе клиента)").fill(`+998 71 100 00 ${RUN}`);
  await page.getByRole("button", { name: "Сохранить" }).click();
  await step(page, r, "раздел «Компания» сохранён", async () => { await page.getByText("Настройки «Компания» сохранены").waitFor({ timeout: 15000 }); });
  await toastsGone(page);
  await screen(page, r, "bot-company");

  // обход всех разделов: открывается, без ошибок, axe 1440
  const sections = await botNav(page).getByRole("link").allInnerTexts();
  for (const name of sections) {
    if (["Шаблоны ответов", "Выгрузки CSV"].includes(name)) continue;
    await openBot(page, name);
    const alerts = await page.getByRole("alert").allInnerTexts();
    r.check(`раздел «${name}»: открывается без ошибок загрузки`, !alerts.some((x) => /не удалось|ошибка|недоступ/i.test(x)), alerts.join(" | "));
  }
  await openBot(page, "Рабочие часы");
  const sat = page.getByRole("group", { name: "Рабочие дни" }).getByRole("checkbox", { name: "Сб" });
  await page.waitForTimeout(800);
  await sat.click({ force: true });
  await page.waitForTimeout(400);
  await page.getByRole("button", { name: "Сохранить" }).click();
  await step(page, r, "«Рабочие часы»: изменение сохранено", async () => { await page.getByText("Настройки «Рабочие часы» сохранены").waitFor({ timeout: 15000 }); });
  await toastsGone(page);
  await sat.click({ force: true });
  await page.waitForTimeout(400);
  await page.getByRole("button", { name: "Сохранить" }).click();
  await page.getByText("Настройки «Рабочие часы» сохранены").waitFor({ timeout: 15000 }).catch(() => {});
  await screen(page, r, "bot-hours");

  await openBot(page, "Поведение бота");
  await page.getByLabel("Максимум слов в ответе").fill(String(60 + Number(RUN) % 30));
  await page.getByRole("button", { name: "Сохранить" }).click();
  await step(page, r, "«Поведение бота»: сохранено", async () => { await page.getByText("Настройки «Поведение бота» сохранены").waitFor({ timeout: 15000 }); });
  await toastsGone(page);

  // тексты бота: таблица, правка в боковом окне с предпросмотром
  await openBot(page, "Тексты бота");
  await step(page, r, "«Тексты бота»: таблица по группам, поиск", async () => {
    await page.getByRole("searchbox", { name: "Найти текст по названию или ситуации" }).fill("Приветствие");
    await page.getByRole("button", { name: "Изменить: Приветствие" }).waitFor({ timeout: 10000 });
  });
  await page.getByRole("button", { name: "Изменить: Приветствие" }).click();
  const panel = side(page);
  await panel.getByRole("heading", { level: 3, name: "Приветствие" }).waitFor({ timeout: 10000 });
  await screen(page, r, "bot-texts-panel");
  await panel.getByLabel("Приветствие · Узбекский").fill("");
  await panel.getByRole("button", { name: "Сохранить раздел" }).click();
  await step(page, r, "пустой перевод отклоняется словами («Нет перевода»)", async () => { await panel.getByText("Нет перевода").first().waitFor({ timeout: 8000 }); });
  await panel.getByLabel("Приветствие · Узбекский").fill("Salom! {company} sizni qutlaydi.");
  await panel.getByRole("button", { name: "Сохранить раздел" }).click();
  await step(page, r, "«Тексты бота»: сохранено с переводом", async () => { await page.getByText("Настройки «Тексты бота» сохранены").waitFor({ timeout: 15000 }); });
  await toastsGone(page);

  // правила передачи: пробный прогон
  await openBot(page, "Правила передачи");
  const dry = page.getByRole("region", { name: "Пробный прогон правил передачи" });
  await step(page, r, "пробный прогон: «Что произойдёт»", async () => { await dry.getByRole("group", { name: "Что произойдёт" }).waitFor(); });
  await dry.getByRole("button", { name: /Проверить на последних/ }).click();
  await page.waitForTimeout(5000);
  r.note("пробный прогон эскалаций на пустой базе диалогов", (await dry.innerText()).replace(/\n+/g, " | ").slice(0, 500));
  r.check("пробный прогон отработал и ничего не сохранил (итог словами)", (await dry.getByRole("status").count()) > 0 || /диалог|изменится|ничего/i.test(await dry.innerText()), "");
  await screen(page, r, "bot-escalation-dry-run");

  // шаблоны ответов: создать, изменить, удалить
  await openBot(page, "Шаблоны ответов");
  await page.getByRole("link", { name: "Новый шаблон" }).first().click();
  const panel2 = side(page);
  const nf = panel2.getByRole("form", { name: "Новый шаблон" });
  await nf.getByRole("group", { name: "Что произойдёт" }).waitFor();
  await nf.getByLabel("Название").fill(`Скидка по запросу ${RUN}`);
  await nf.getByLabel("Текст — Русский").fill("{name}, скидку согласует {manager}.");
  await nf.getByRole("button", { name: "Создать шаблон" }).click();
  await step(page, r, "шаблон ответа создан", async () => { await page.getByText("Шаблон создан").waitFor({ timeout: 15000 }); await page.getByRole("link", { name: `Открыть шаблон: Скидка по запросу ${RUN}` }).waitFor({ timeout: 10000 }); });
  await toastsGone(page);
  await page.getByRole("link", { name: `Открыть шаблон: Скидка по запросу ${RUN}` }).click();
  const ef = panel2.getByRole("form", { name: "Изменить шаблон" });
  await ef.getByLabel("Название").fill(`Скидка по согласованию ${RUN}`);
  await ef.getByRole("button", { name: "Сохранить шаблон" }).click();
  await step(page, r, "шаблон ответа изменён", async () => { await page.getByText("Шаблон сохранён").waitFor({ timeout: 15000 }); });
  await toastsGone(page);
  await screen(page, r, "bot-reply-templates");
  await panel2.getByRole("button", { name: "Удалить шаблон" }).click();
  const df = panel2.getByRole("form", { name: "Удалить шаблон" });
  await df.getByRole("group", { name: "Что произойдёт" }).waitFor();
  await df.getByRole("button", { name: "Удалить шаблон" }).click();
  await step(page, r, "шаблон ответа удалён", async () => { await page.getByText("Шаблон удалён").waitFor({ timeout: 15000 }); });

  // выгрузки CSV: администратор без роли данных — кнопки недоступны и объяснены
  await openBot(page, "Выгрузки CSV");
  await step(page, r, "выгрузки: у администратора без роли с данными CRM кнопки недоступны, причина словами", async () => {
    for (const t of ["Лиды", "Клиенты", "Сделки"]) if (!(await page.getByRole("button", { name: `Скачать: ${t}` }).isDisabled())) throw new Error(`доступна «${t}»`);
    await page.getByText(/нужен раздел «CRM · Все лиды»/).waitFor();
  });
  await screen(page, r, "bot-exports-admin");
  r.note("ошибки консоли / 5xx", `${page.consoleErrors.join(" | ")} ;; ${page.failed.join(" | ")}`);
  r.save();

  // «выдайте администратору вторую роль»: сотрудник с ролями Администратор + Менеджер (создаём из Платформы, без почты) скачивает CSV
  const r2 = new Report("s6csv");
  const uni = { name: "Демо Универсалов", email: "universal.demo@demo.example" };
  if (!state().staff?.universal) {
    await spaGoto(page, "/admin/org?invite=open&panel=open");
    const ip = side(page);
    await ip.getByRole("heading", { level: 3, name: "Пригласить сотрудника" }).waitFor();
    await ip.getByRole("radio", { name: "Временным паролем, без почты" }).check();
    await ip.getByLabel("Имя и фамилия").fill(uni.name);
    await ip.getByLabel("Электронная почта").fill(uni.email);
    await ip.getByRole("checkbox", { name: /^Администратор/ }).check();
    await ip.getByRole("checkbox", { name: /^Менеджер/ }).check();
    await ip.getByRole("button", { name: "Создать и показать пароль" }).click();
    const f = ip.getByLabel("Временный пароль", { exact: true });
    await f.waitFor({ timeout: 30000 });
    const temp = await f.inputValue();
    await ip.getByRole("button", { name: "Готово: пароль передан" }).click();
    saveState({ staff: { ...state().staff, universal: { ...uni, temp } } });
  }
  const { page: p2 } = await newPage(browser);
  const u = state().staff.universal;
  if (u.temp && !u.pw) {
    await login(p2, u.email, u.temp);
    await p2.waitForURL(/\/change-password$/, { timeout: 15000 });
    const own = secret("own");
    await p2.getByLabel("Текущий пароль").fill(u.temp);
    await p2.getByLabel("Новый пароль", { exact: true }).fill(own);
    await p2.getByLabel("Повторите новый пароль").fill(own);
    await p2.getByRole("button", { name: "Сменить пароль" }).click();
    await p2.waitForURL((x) => !/change-password/.test(x.pathname), { timeout: 15000 });
    saveState({ staff: { ...state().staff, universal: { ...u, pw: own } } });
  } else {
    await loginOk(p2, u.email, u.pw);
  }
  await openBot(p2, "Выгрузки CSV");
  for (const [ent, title] of [["leads", "Лиды"], ["clients", "Клиенты"], ["deals", "Сделки"]]) {
    const card = p2.locator(`article[data-entity="${ent}"]`);
    const dl = p2.waitForEvent("download", { timeout: 30000 }).catch(() => null);
    await card.getByRole("button", { name: `Скачать: ${title}` }).click();
    const file = await dl;
    r2.check(`CSV «${title}»: файл скачан`, !!file, file ? file.suggestedFilename() : "скачивания не было");
    if (file) {
      const path = await file.path();
      const { readFileSync } = await import("node:fs");
      const txt = readFileSync(path, "utf8");
      r2.check(`CSV «${title}»: имя с датой, разделитель «;», заголовки`, new RegExp(`^${ent}-\\d{8}-\\d{4}\\.csv$`).test(file.suggestedFilename()) && txt.split("\n")[0].includes(";"), `${file.suggestedFilename()}, ${txt.split("\n").filter(Boolean).length} строк (с заголовком), первая строка: ${txt.split("\n")[0].slice(0, 140)}`);
    }
  }
  await screen(p2, r2, "bot-exports-admin-manager");
  r2.save();
};


// ---------------------------------------------------------------------------------------------------------------------
// 7. Директор (системная роль): расходы и журнал аудита на чтение; интеграции, модели, бэкапы на чтение; кнопок изменения нет;
//    BFF на изменения отвечает 403. 8. Роль без раздела Admin (Менеджер): пунктов Admin нет, прямой URL — «Нет доступа».
async function railTexts(page) {
  const links = page.getByRole("navigation", { name: "Модули" }).getByRole("link").filter({ hasNotText: /^RT$/ });
  return (await links.allInnerTexts()).map((x) => x.trim());
}

scenarios.s7 = async (browser) => {
  const r = new Report("s7");
  const { page } = await newPage(browser);
  const d = state().staff.director;
  await loginOk(page, d.email, d.pw);
  r.note("рейл директора", (await railTexts(page)).join(", "));
  await spaGoto(page, "/admin/roles");
  await page.getByRole("heading", { level: 1 }).first().waitFor();
  const sub = (await page.getByRole("navigation", { name: "Разделы модуля" }).getByRole("link").allInnerTexts()).map((x) => x.trim());
  r.note("подменю Admin у директора", sub.join(", "));
  r.check("в подменю Admin у директора нет «Журнала интеграций» (admin: full)", !sub.includes("Журнал интеграций"), sub.join(", "));
  r.check("в подменю Admin у директора есть «Внешние интеграции», «Журнал аудита»", sub.includes("Внешние интеграции") && sub.includes("Журнал аудита"), sub.join(", "));

  // интеграции на чтение
  await openCard(page, null);
  await step(page, r, "интеграции: плашка «Только просмотр», кнопок «Проверить» нет", async () => {
    await page.getByText("Только просмотр").first().waitFor({ timeout: 10000 });
    if ((await page.getByRole("button", { name: /^Проверить/ }).count()) !== 0) throw new Error("есть кнопки «Проверить»");
  });
  await screen(page, r, "director-integrations");
  for (const [card, what] of [["erp", "ERP"], ["telegram", "Telegram"], ["mail", "Почта"], ["models", "Модели ИИ"], ["storage", "Бэкапы"], ["spend", "Расходы"], ["system", "Состояние"]]) {
    await openCard(page, card);
    const btns = (await side(page).getByRole("button").allInnerTexts()).map((x) => x.trim()).filter(Boolean);
    const mutating = btns.filter((x) => /Подключить|Ротация|Сменить|Сбросить|Задать|Настроить|Тестовое|Проверить|Сделать копию|Выключить|Включить|Запросить/.test(x));
    r.check(`${what}: открывается на чтение, кнопок изменения нет`, mutating.length === 0, mutating.length ? `есть: ${mutating.join(" | ")}` : (await side(page).innerText()).replace(/\n+/g, " | ").slice(0, 160));
    if (card === "models" || card === "spend" || card === "storage") await screen(page, r, `director-${card}`, { narrow: card === "spend" });
  }

  // расходы и журнал аудита на чтение
  await spaGoto(page, "/admin/audit");
  await step(page, r, "журнал аудита: директор читает записи", async () => { await page.getByRole("table", { name: "Записи журнала аудита" }).getByRole("row").nth(3).waitFor({ timeout: 15000 }); });
  await screen(page, r, "director-audit");
  await spaGoto(page, "/admin/org");
  await page.getByRole("link", { name: "Открыть карточку: Демо Менеджеров" }).click();
  const card = side(page);
  await step(page, r, "оргструктура: «Только просмотр», ролей и «Сбросить пароль» нет", async () => {
    await card.getByText("Только просмотр").first().waitFor({ timeout: 10000 });
    if ((await card.getByRole("checkbox").count()) || (await card.getByRole("button", { name: "Сбросить пароль" }).count())) throw new Error("есть элементы изменения");
  });
  await shot(page, r, "director-org-readonly");

  // BFF: изменения — 403
  const probes = [
    ["POST", "/api/v1/admin/integrations/erp/rotate", { password: "x" }],
    ["PUT", "/api/v1/admin/integrations/models/qualifier-model", { provider: "anthropic", model: "x", password: "x" }],
    ["POST", "/api/v1/admin/integrations/models/qualifier-model/reset", { password: "x" }],
    ["POST", "/api/v1/admin/integrations/backups", {}],
    ["POST", "/api/v1/admin/integrations/smtp/check", {}],
    ["PUT", "/api/v1/admin/integrations/telegram/token", { token: "x", password: "x" }],
    ["POST", "/api/v1/admin/users/1/temporary-password", { password: "x" }],
    ["POST", "/api/v1/admin/users/1/reset-password/email", { password: "x" }],
  ];
  for (const [m, path, body] of probes) {
    const res = await bff(page, m, path, body);
    r.check(`BFF ${m} ${path} от директора -> 403 (не 2xx и не 5xx)`, res.status === 403, `HTTP ${res.status} ${JSON.stringify(res.body)?.slice(0, 120)}`);
  }
  const bus = await bff(page, "GET", "/api/v1/admin/bus");
  r.check("BFF GET /admin/bus от директора -> 403 (журнал шины только admin: full)", bus.status === 403, `HTTP ${bus.status}`);
  const rotate = await bff(page, "POST", "/api/v1/admin/integrations/erp/rotate", { password: "x" });
  r.check("ротация ключей ERP от директора -> именно 403", rotate.status === 403, `HTTP ${rotate.status} ${JSON.stringify(rotate.body)?.slice(0, 160)}`);
  await spaGoto(page, "/admin/bus");
  await step(page, r, "прямой URL /admin/bus у директора — «Нет доступа»", async () => { await page.getByRole("heading", { level: 1, name: "Нет доступа" }).waitFor({ timeout: 10000 }); });
  r.note("ошибки консоли / 5xx", `${page.consoleErrors.join(" | ")} ;; ${page.failed.join(" | ")}`);
  r.save();
};

scenarios.s8 = async (browser) => {
  const r = new Report("s8");
  const { page } = await newPage(browser);
  const m = state().staff.manager;
  await loginOk(page, m.email, m.pw);
  const rail = await railTexts(page);
  r.check("у Менеджера в рейле нет «Admin»", !rail.some((x) => /Admin/.test(x)), rail.join(", "));
  for (const path of ["/admin/org", "/admin/roles", "/admin/integrations", "/admin/company", "/admin/bot", "/admin/audit", "/admin/bus", "/admin/setup"]) {
    await spaGoto(page, path);
    const ok = await page.getByRole("heading", { level: 1, name: "Нет доступа" }).waitFor({ timeout: 8000 }).then(() => true).catch(() => false);
    r.check(`прямой URL ${path} -> экран «Нет доступа»`, ok, ok ? "" : (await page.getByRole("heading", { level: 1 }).first().innerText().catch(() => "")));
  }
  await shot(page, r, "no-access");
  await screen(page, r, "no-access-screen", { narrow: true });
  // BFF: чтение и изменение — 403
  for (const [mth, path] of [["GET", "/api/v1/admin/integrations"], ["GET", "/api/v1/admin/audit"], ["GET", "/api/v1/admin/bus"], ["GET", "/api/v1/admin/company"], ["POST", "/api/v1/admin/integrations/erp/rotate"]]) {
    const res = await bff(page, mth, path, mth === "POST" ? { password: "x" } : undefined);
    r.check(`BFF ${mth} ${path} от Менеджера -> 403`, res.status === 403, `HTTP ${res.status}`);
  }
  // меню: у «Менеджера» нет ссылок на Admin ни в быстром действии
  r.check("в меню нет ссылок на /admin", (await page.locator('a[href^="/admin"]').count()) === 0, String(await page.locator('a[href^="/admin"]').count()));
  r.note("ошибки консоли / 5xx", `${page.consoleErrors.join(" | ")} ;; ${page.failed.join(" | ")}`);
  r.save();
};


// ---------------------------------------------------------------------------------------------------------------------
// 4. Журнал интеграций: подписчики трёх доменов, доставки с фильтрами, DLQ, «Повторить» / «Повторить все dead», inbox.
// Предусловие: `bus_dead.sh on` (адрес EDS у издателей -> заглушка, отвечающая 400). Сценарий создаёт события правкой ролей
// сотрудника в Платформе, проверяет DLQ, чинит адрес (`bus_dead.sh off`) и повторяет доставки из Платформы.
const domainCard = (page, domain) => page.getByRole("region", { name: `${domain} отправляет` });
async function openJournal(page, view) {
  await spaGoto(page, view ? `/admin/bus?view=${view}` : "/admin/bus");
  await page.getByRole("heading", { level: 1, name: "Журнал интеграций" }).waitFor();
  await page.waitForTimeout(1800);
  await page.locator(".ant-skeleton").first().waitFor({ state: "detached", timeout: 15000 }).catch(() => {});
}

scenarios.s4 = async (browser) => {
  const r = new Report("s4");
  const { page } = await newPage(browser);
  const st = state();
  await loginOk(page, st.adminEmail, st.adminPw);
  const panel = side(page);

  // события: правка ролей сотрудника -> identity.user.updated уходит EDS и Платформе (EDS -> заглушка -> 400 -> dead)
  await openOrgCard(page, "Демо Бухгалтеров");
  const mgr = panel.getByRole("checkbox", { name: /^Менеджер/ });
  if (await mgr.isChecked()) await mgr.uncheck(); else await mgr.check();
  await panel.getByRole("button", { name: "Сохранить роли" }).click();
  await step(page, r, "правка ролей сотрудника сохранена (источник событий identity.user.updated)", async () => { await page.getByText("Сохранено").first().waitFor({ timeout: 20000 }); });
  await page.waitForTimeout(12000);

  await openJournal(page);
  await step(page, r, "подписчики трёх доменов: CRM, ERP и EDS отправляют, состояние словом", async () => {
    for (const dom of ["CRM", "ERP", "EDS"]) await domainCard(page, dom).waitFor({ timeout: 10000 });
  });
  const crmText = (await domainCard(page, "CRM").innerText()).replace(/\n+/g, " | ");
  r.note("CRM отправляет", crmText.slice(0, 700));
  r.check("у подписчика EDS в карточке CRM есть недоставленные (dead) — состояние словом", /Есть недоставленные|Ошибки подряд|Пауза/.test(crmText), crmText.slice(0, 300));
  await screen(page, r, "bus-subscribers-broken");
  const dlqLink = page.getByRole("link", { name: /Недоставлено \(DLQ\)/ });
  r.note("счётчик DLQ в шапке", (await dlqLink.innerText().catch(() => "—")).replace(/\n+/g, " "));

  await openJournal(page, "dlq");
  const dlq = page.getByRole("table", { name: "Недоставленные события (DLQ)" });
  await step(page, r, "DLQ: dead-доставки видны, статус «Не доставлено»", async () => { await dlq.getByText("Не доставлено").first().waitFor({ timeout: 15000 }); });
  const nDead = await dlq.getByText("Не доставлено").count();
  r.note("в DLQ доставок", String(nDead));
  await screen(page, r, "bus-dlq");
  await dlq.getByRole("button", { name: /^Подробнее:/ }).first().click();
  await step(page, r, "доставка: тип события, ошибка словами, тело события не показывается", async () => {
    await panel.getByText(/uz\.railtech\./).first().waitFor({ timeout: 10000 });
    await panel.getByText(/Тело события в журнал не выводится/).waitFor({ timeout: 5000 });
  });
  r.note("карточка dead-доставки", (await panel.innerText()).replace(/\n+/g, " | ").slice(0, 600));
  await shot(page, r, "bus-delivery-panel");
  await panel.getByRole("button", { name: /Повторить доставку/ }).click();
  await page.waitForTimeout(6000);
  r.note("«Повторить доставку» при ещё неисправном адресе (должна вернуться в DLQ)", (await panel.innerText()).replace(/\n+/g, " | ").slice(-300));

  // чиним адрес EDS и повторяем из Платформы
  execFileSync(process.env.QA_BUS_DEAD ?? fileURLToPath(new URL("./bus_dead.sh", import.meta.url)), ["off"], { encoding: "utf8", env: process.env });
  await page.waitForTimeout(25000);
  await openJournal(page);
  await page.getByRole("button", { name: /^Повторить все dead: EDS/ }).first().click();
  await step(page, r, "«Повторить все dead»: «Что произойдёт» и число доставок", async () => {
    await panel.getByRole("heading", { name: /Повторить все недоставленные · EDS/ }).waitFor({ timeout: 10000 });
    await panel.getByRole("group", { name: "Что произойдёт" }).waitFor();
  });
  r.note("текст блока «Что произойдёт» (повтор всех dead)", (await panel.getByRole("group", { name: "Что произойдёт" }).innerText()).replace(/\n+/g, " | "));
  await shot(page, r, "bus-retry-dead");
  await panel.getByRole("button", { name: /^Повторить \d+/ }).click();
  await step(page, r, "повтор поставлен: «Поставлены на повтор N доставки»", async () => { await panel.getByText(/Поставлены на повтор/).waitFor({ timeout: 20000 }); });
  await shot(page, r, "bus-retry-dead-done");
  await page.waitForTimeout(20000);
  await openJournal(page, "dlq");
  await step(page, r, "после повтора DLQ пуст — доставлено", async () => { await page.getByRole("heading", { name: "Недоставленных нет" }).waitFor({ timeout: 20000 }); });
  await openJournal(page, "deliveries");
  const table = page.getByRole("table", { name: "Доставки событий подписчикам" });
  await page.getByLabel("Домен").selectOption({ label: "CRM" }).catch(() => {});
  await page.getByLabel("Подписчик").selectOption({ label: "EDS" }).catch(() => {});
  await page.waitForTimeout(2000);
  const delivered = await table.getByText("Доставлено").count();
  r.check("доставки CRM -> EDS в статусе «Доставлено» после повтора", delivered >= 1, `Доставлено: ${delivered}`);
  await page.getByLabel("Тип события содержит").fill("identity").catch(() => {});
  await page.waitForTimeout(1500);
  await shot(page, r, "bus-deliveries-filtered");
  await page.getByLabel("Тип события содержит").fill("nothing-like-this");
  await step(page, r, "фильтр без совпадений: «Доставок не найдено» и «Сбросить фильтры»", async () => { await page.getByRole("heading", { name: "Доставок не найдено" }).waitFor({ timeout: 10000 }); });
  await page.getByRole("button", { name: "Сбросить фильтры" }).first().click();
  await screen(page, r, "bus-deliveries");

  // входящие с ошибками
  await openJournal(page, "inbox");
  await step(page, r, "«Входящие с ошибками»: экран и пустое состояние словами", async () => { await page.getByRole("heading", { name: "Ошибок обработки нет" }).waitFor({ timeout: 10000 }); });
  await screen(page, r, "bus-inbox");

  // EDS: плашки «EDS не дал доступ» нет
  await openJournal(page);
  const txt = await page.locator("main").innerText();
  r.check("в журнале нет плашки «EDS не дал доступ»", !/не дал доступ/i.test(txt), /не дал доступ/i.test(txt) ? "плашка есть — нужен republish-identity (deploy.md)" : "плашки нет, EDS-подписчики видны");
  await screen(page, r, "bus-subscribers-fixed");
  r.note("ошибки консоли / 5xx", `${page.consoleErrors.join(" | ")} ;; ${page.failed.join(" | ")}`);
  r.save();
};


// 2b. Ротация ключей ERP и SMTP «сохранить настройки» — выполняются в конце гейта: меняют состояние стенда (ключи ERP; почта
// остаётся настроенной на недоступный сервер, это видно на снимках). Серверов почты в стенде нет — «Проверить связь» честно не проходит.
scenarios.s2tail = async (browser) => {
  const r = new Report("s2tail");
  const { page } = await newPage(browser);
  const st = state();
  await loginOk(page, st.adminEmail, st.adminPw);
  const panel = side(page);
  await openCard(page, "erp");
  await panel.getByRole("button", { name: "Подключить заново" }).click();
  await panel.getByRole("button", { name: "Ротация ключа" }).click();
  const rot = panel.getByRole("form", { name: "Ротация ключей ERP" });
  await step(page, r, "ротация ключей ERP: «Что произойдёт»", async () => { await rot.getByRole("group", { name: "Что произойдёт" }).waitFor(); });
  await shot(page, r, "erp-rotate-form", { mask: [pwField(rot)] });
  await pwField(rot).fill(st.adminPw);
  await rot.getByRole("button", { name: "Обновить ключи" }).click();
  await step(page, r, "ротация ключей ERP: «Ключи обновлены»", async () => { await panel.getByText("Ключи обновлены.").waitFor({ timeout: 40000 }); });
  r.note("карточка ERP после ротации", (await panel.innerText()).replace(/\n+/g, " | ").slice(0, 400));
  await panel.getByRole("button", { name: "Проверить связь" }).click();
  await step(page, r, "после ротации «Проверить связь» зелёное (шина и сопряжение живы)", async () => { await panel.getByText("ERP отвечает", { exact: true }).waitFor({ timeout: 20000 }); });

  await openCard(page, "mail");
  if (!(await panel.getByText("smtp.invalid.example:587").isVisible().catch(() => false))) {
    await panel.getByRole("button", { name: "Настроить SMTP" }).click();
    const smtp = panel.getByRole("form", { name: "Настройки SMTP" });
    await smtp.getByLabel("Сервер (хост)").fill("smtp.invalid.example");
    await smtp.getByLabel("Порт").fill("587");
    await smtp.getByLabel("Адрес отправителя").fill("noreply@demo.example");
    await smtp.getByLabel("Имя отправителя").fill("RailTech Демо");
    await smtp.getByLabel("Логин").fill("demo-user");
    await smtp.getByLabel("Пароль SMTP").fill(secret("smtp"));
    await pwField(smtp).fill(st.adminPw);
    await smtp.getByRole("button", { name: "Сохранить настройки" }).click();
  }
  await step(page, r, "SMTP: настройки сохранены, пароль показан маской", async () => {
    await panel.getByText("smtp.invalid.example:587").waitFor({ timeout: 30000 });
    await panel.getByText(/••••/).first().waitFor({ timeout: 5000 });
  });
  await shot(page, r, "mail-smtp-saved");
  await panel.getByRole("button", { name: "Проверить связь" }).click();
  await page.waitForTimeout(12000);
  r.note("SMTP · «Проверить связь» на недоступный сервер", (await panel.innerText()).replace(/\n+/g, " | ").slice(0, 700));
  await shot(page, r, "mail-smtp-check-fails");
  await panel.getByRole("button", { name: "Тестовое письмо" }).click();
  await page.waitForTimeout(6000);
  r.note("SMTP · «Тестовое письмо» на недоступный сервер", (await panel.innerText()).replace(/\n+/g, " | ").slice(-500));
  await screen(page, r, "mail-smtp-after-test");
  // приглашение по почте при настроенном, но недоступном SMTP: сотрудник создан, письмо не ушло — сказано словами
  await spaGoto(page, "/admin/org?invite=open&panel=open");
  await panel.getByRole("heading", { level: 3, name: "Пригласить сотрудника" }).waitFor();
  await panel.getByLabel("Имя и фамилия").fill(`Демо Письмов ${RUN}`);
  await panel.getByLabel("Электронная почта").fill(`mailtest${RUN}.demo@demo.example`);
  await panel.getByRole("checkbox", { name: /^Менеджер/ }).check();
  await panel.getByRole("button", { name: "Отправить приглашение" }).click();
  await step(page, r, "приглашение по почте при недоступном SMTP — понятная ошибка", async () => { await panel.getByRole("alert").first().waitFor({ timeout: 40000 }); });
  r.note("текст ошибки приглашения (SMTP настроен, сервер недоступен)", (await panel.getByRole("alert").first().innerText()).replace(/\n+/g, " | "));
  await shot(page, r, "invite-mail-smtp-down");
  r.check("страница не вернула 5xx (кроме честного 502 «сервер почты не отвечает»)", !page.failed.some((x) => /^(500|503|504)/.test(x)), page.failed.join(" | "));
  r.save();
};


// 5c. Отключение и возврат сотрудника: отключённый не входит («Неверная почта или пароль»), включённый снова входит.
scenarios.s5c = async (browser) => {
  const r = new Report("s5c");
  const { page } = await newPage(browser);
  const st = state();
  await loginOk(page, st.adminEmail, st.adminPw);
  const target = st.staff.accountant; // временный пароль не менялся: вход ведёт на обязательную смену
  const panel = side(page);
  await openOrgCard(page, "Демо Бухгалтеров");
  await panel.getByRole("button", { name: "Отключить сотрудника" }).click();
  await step(page, r, "отключение: «Что произойдёт» (вход в Платформу, CRM и ERP закроется)", async () => { await panel.getByText("Вход в Платформу, CRM и ERP закроется.").waitFor({ timeout: 10000 }); });
  await shot(page, r, "org-disable-confirm");
  await panel.getByRole("button", { name: "Отключить", exact: true }).click();
  await step(page, r, "сотрудник отключён, статус «Отключён»", async () => { await panel.getByText("Сотрудник отключён и не может войти.").waitFor({ timeout: 15000 }); await page.getByRole("row", { name: /Демо Бухгалтеров/ }).getByText("Отключён").waitFor({ timeout: 10000 }); });
  const { page: p2 } = await newPage(browser);
  await login(p2, target.email, target.temp);
  await step(p2, r, "отключённый сотрудник не входит — «Неверная почта или пароль»", async () => { await p2.getByRole("alert").filter({ hasText: /Неверная почта или пароль/ }).waitFor({ timeout: 10000 }); });
  await openOrgCard(page, "Демо Бухгалтеров");
  await panel.getByRole("button", { name: "Включить сотрудника" }).click();
  const enable = panel.getByRole("button", { name: /^(Включить|Вернуть)/ }).last();
  await step(page, r, "кнопка возврата доступа есть", async () => { await enable.waitFor({ timeout: 10000 }); });
  await shot(page, r, "org-enable-confirm");
  await enable.click();
  await step(page, r, "сотрудник снова активен/приглашён (не «Отключён»)", async () => { await page.waitForTimeout(2500); if (await page.getByRole("row", { name: /Демо Бухгалтеров/ }).getByText("Отключён").count()) throw new Error("остался отключённым"); });
  await login(p2, target.email, target.temp);
  await step(p2, r, "включённый снова входит (временный пароль -> обязательная смена)", async () => { await p2.waitForURL(/\/change-password$/, { timeout: 15000 }); });
  r.save();
};

const only = process.argv.slice(2);
const browser = await launch();
try {
  for (const name of only) {
    if (!scenarios[name]) throw new Error(`нет сценария ${name}`);
    console.log(`=== ${name}`);
    await scenarios[name](browser);
  }
} finally {
  await browser.close();
}
