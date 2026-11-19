// Сценарий 1. Лид → заявка → расчёт → КП → одобрение → отправка клиенту.
import { PANEL, Report, as, obs, screen, seen, settle, spaGoto, step, saveState, state } from "./common.mjs";
export const scenarios = {};

// 1a. Менеджер заводит лид со звонка: «Создать → Лид».
scenarios["1a"] = async (browser) => {
  const r = new Report("1a");
  const page = await as(browser, r, "manager_all");
  await spaGoto(page, "/crm/leads?new=1&panel=open&tab=card");
  await settle(page);
  const panel = page.locator(PANEL);
  await step(page, r, "форма лида заполняется", async () => {
    await panel.getByText("Звонок", { exact: true }).click();
    await panel.getByLabel("Имя", { exact: true }).fill("Азиз Каримов");
    await panel.getByLabel("Компания").fill("ООО Сценарий Путь");
    await panel.getByLabel("Телефон").fill("+998901112233");
    await panel.getByLabel("Почта").fill("aziz.sc2@demo.example");
    await panel.getByLabel("Что нужно").fill("Рельсы Р65, 40 т, доставка до станции Ташкент-Товарный");
  });
  await screen(page, r, "lead-form", { narrow: false });
  await step(page, r, "«Создать лид»", async () => {
    await panel.getByRole("button", { name: "Создать лид" }).click();
    await page.waitForTimeout(3000);
    await settle(page);
  });
  const url = page.url();
  const lead = url.match(/lead=([A-Z]-?\d+)/)?.[1] ?? "";
  saveState({ sc2Lead: lead });
  obs(r, "лид создан", { sees: `${url}\n${await seen(page, PANEL)}` });
  await screen(page, r, "lead-created", { narrow: true });
  r.save();
};

// 1b. Менеджер: из карточки лида «Создать заявку» (согласия на данные у лида со звонка нет).
scenarios["1b"] = async (browser) => {
  const r = new Report("1b");
  const page = await as(browser, r, "manager_all");
  const lead = state().sc2Lead || "L-0001";
  await spaGoto(page, `/crm/leads?lead=${lead}&panel=open&tab=card`);
  await settle(page);
  const panel = page.locator(PANEL);
  await step(page, r, "«Создать заявку» из карточки лида", async () => {
    await page.getByText("Создать заявку", { exact: true }).last().click();
    await page.waitForTimeout(2000);
    await settle(page);
  });
  obs(r, "после «Создать заявку»", { sees: `${page.url()}\n${await seen(page, "body", 3000)}` });
  await screen(page, r, "request-form", { narrow: false });
  r.save();
};

// 1c. Менеджер проходит форму заявки до конца: ИНН, контакт, запрос, «Проверка и отправка».
scenarios["1c"] = async (browser) => {
  const r = new Report("1c");
  const page = await as(browser, r, "manager_all");
  const lead = state().sc2Lead || "L-0001";
  await spaGoto(page, `/crm/leads?lead=${lead}&create=1&panel=open&tab=card`);
  await settle(page);
  const panel = page.locator(PANEL);
  await step(page, r, "клиент: ИНН и «Далее»", async () => {
    await panel.getByLabel("ИНН").fill("301234567");
    await panel.getByRole("button", { name: "Далее: Контакт" }).click();
    await page.waitForTimeout(800);
  });
  obs(r, "после шага «Клиент»", { sees: await seen(page, PANEL, 1500) });
  // дальше — по кнопкам «Далее…», пока не дойдём до последней
  for (let i = 0; i < 4; i++) {
    const next = panel.getByRole("button", { name: /^Далее/ }).first();
    if (!(await next.isVisible().catch(() => false))) break;
    await next.click();
    await page.waitForTimeout(800);
  }
  obs(r, "шаг «Проверка и отправка»", { sees: await seen(page, PANEL, 2000) });
  await screen(page, r, "request-review", { narrow: false });
  const posts = [];
  page.on("response", async (q) => {
    if (q.request().method() === "POST" && /crm\/requests/.test(q.url())) posts.push(`${q.status()} ${(await q.text().catch(() => "")).slice(0, 300)}`);
  });
  await step(page, r, "«Создать заявку» (финальная кнопка)", async () => {
    await panel.getByRole("button", { name: /^Создать заявку/ }).last().click();
    await page.waitForTimeout(5000);
    await settle(page);
  });
  obs(r, "после создания заявки", { sees: `${page.url()}\nPOST: ${posts.join(" | ")}\n${await seen(page, "body", 3500)}` });
  await screen(page, r, "request-created", { narrow: true });
  r.save();
};

// 1d. Менеджер: тот же путь с файлом запроса и отметкой «Согласие получено».
scenarios["1d"] = async (browser) => {
  const r = new Report("1d");
  const page = await as(browser, r, "manager_all");
  const lead = state().sc2Lead || "L-0001";
  await spaGoto(page, `/crm/leads?lead=${lead}&create=1&panel=open&tab=card`);
  await settle(page);
  const panel = page.locator(PANEL);
  await panel.getByLabel("ИНН").fill("301234567");
  for (let i = 0; i < 4; i++) {
    const next = panel.getByRole("button", { name: /^Далее/ }).first();
    if (!(await next.isVisible().catch(() => false))) break;
    await next.click();
    await page.waitForTimeout(800);
  }
  await panel.getByRole("button", { name: /^Создать заявку/ }).last().click();
  await page.waitForTimeout(1500);
  await step(page, r, "файл запроса и согласие", async () => {
    await panel.locator('input[type="file"]').first().setInputFiles(process.env.SC2_LETTER);
    await page.waitForTimeout(3000);
    await panel.getByLabel("Согласие получено").check();
    await panel.getByRole("button", { name: /^Далее: Проверка/ }).click();
    await page.waitForTimeout(800);
  });
  const posts = [];
  page.on("response", async (q) => {
    if (q.request().method() === "POST" && /crm\/requests/.test(q.url())) posts.push(`${q.status()} ${(await q.text().catch(() => "")).slice(0, 300)}`);
  });
  await step(page, r, "«Создать заявку»", async () => {
    await panel.getByRole("button", { name: /^Создать заявку/ }).last().click();
    await page.waitForTimeout(6000);
    await settle(page);
  });
  obs(r, "после создания заявки", { sees: `${page.url()}\nPOST: ${posts.join(" | ")}\n${await seen(page, "body", 3500)}` });
  const number = (await page.locator("body").innerText()).match(/ЗВ-\d{4}-\d{3}/)?.[0] ?? "";
  saveState({ sc2Request: number });
  await screen(page, r, "request-created", { narrow: true });
  r.save();
};

// 1e. Что дальше после заявки: карточка клиента (номер ЗВ) и «Задачи» менеджера.
scenarios["1e"] = async (browser) => {
  const r = new Report("1e");
  const page = await as(browser, r, "manager_all");
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  obs(r, "«Задачи» менеджера после заявки", { sees: await seen(page, "main", 1500) });
  await screen(page, r, "queue-after-request", { narrow: false });
  await spaGoto(page, "/crm/clients");
  await settle(page);
  obs(r, "Контрагенты", { sees: `${page.url()}\n${await seen(page, "main", 1200)}` });
  await page.getByText("ООО Сценарий Путь").first().click().catch(() => {});
  await page.waitForTimeout(2500);
  await settle(page);
  const body = await seen(page, "body", 5000);
  const number = body.match(/ЗВ-\d{4}-\d{3}/)?.[0] ?? "";
  if (number) saveState({ sc2Request: number });
  obs(r, "карточка клиента", { sees: `${page.url()}\nномер: ${number}\n${await seen(page, PANEL, 2500)}` });
  await screen(page, r, "client-card", { narrow: false });
  r.save();
};

// 1f. Директор: «Задачи» → резолюция на заявку.
scenarios["1f"] = async (browser) => {
  const r = new Report("1f");
  const page = await as(browser, r, "director");
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  obs(r, "«Задачи» директора", { sees: await seen(page, "main", 1800) });
  await screen(page, r, "director-queue", { narrow: false });
  r.save();
};

// 1g. Директор: строка «Наложить резолюцию» → письмо → резолюция (исполнитель — МУ).
scenarios["1g"] = async (browser) => {
  const r = new Report("1g");
  const page = await as(browser, r, "director");
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  await step(page, r, "строка очереди ведёт на письмо", async () => {
    await page.getByRole("link", { name: /Открыть/ }).first().click();
    await page.waitForTimeout(2500);
    await settle(page);
  });
  obs(r, "письмо-заявка у директора", { sees: `${page.url()}\n${await seen(page, PANEL, 2500)}` });
  await screen(page, r, "resolution-form", { narrow: false });
  const panel = page.locator(PANEL);
  await step(page, r, "резолюция заполнена", async () => {
    await panel.getByLabel("Текст резолюции").fill("Рассчитать поставку Р65 40 т и доставку, КП до пятницы.");
    const combos = panel.getByRole("combobox");
    const n = await combos.count();
    for (let i = 0; i < Math.min(n, 2); i++) {
      await combos.nth(i).click();
      await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option", { hasText: "Демо Универсалов" }).first().click();
    }
  });
  await screen(page, r, "resolution-filled", { narrow: false });
  await step(page, r, "«Утвердить резолюцию»", async () => {
    await panel.getByRole("button", { name: /Утвердить резолюцию|Наложить резолюцию/ }).first().click();
    const confirm = page.getByRole("dialog").filter({ hasText: "Утвердить резолюцию" });
    if (await confirm.waitFor({ state: "visible", timeout: 3000 }).then(() => true).catch(() => false)) {
      obs(r, "подтверждение резолюции", { sees: await seen(page, '[role="dialog"]', 400), dead: "подтверждение обратимого действия" });
      await confirm.getByRole("button", { name: "Утвердить резолюцию" }).click();
    }
    await page.waitForTimeout(4000);
    await settle(page);
  });
  obs(r, "после резолюции", { sees: `${page.url()}\n${await seen(page, "body", 4000)}` });
  await screen(page, r, "resolution-done", { narrow: true });
  r.save();
};

// 1h. Исполнитель (МУ): что пришло после резолюции — «Задачи», колокольчик, расчёт.
scenarios["1h"] = async (browser) => {
  const r = new Report("1h");
  const page = await as(browser, r, "manager_all");
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  obs(r, "«Задачи» МУ после резолюции", { sees: await seen(page, "main", 1500) });
  await screen(page, r, "mu-queue-after-resolution", { narrow: false });
  await step(page, r, "строка задачи ведёт в расчёт", async () => {
    await page.getByRole("link", { name: /Открыть|Считать|Расчёт/ }).first().click();
    await page.waitForTimeout(3000);
    await settle(page);
  });
  obs(r, "экран после строки задачи", { sees: `${page.url()}\n${await seen(page, "main", 2500)}` });
  await screen(page, r, "calc-opened", { narrow: false });
  r.save();
};

// 1i. МУ: «Начать расчёт» — что предлагает экран для строк (каталог на стенде пуст).
scenarios["1i"] = async (browser) => {
  const r = new Report("1i");
  const page = await as(browser, r, "manager_all");
  const req = state().sc2Request || "RQ-2026-001";
  await spaGoto(page, `/erp/calc/${req}`);
  await settle(page);
  await step(page, r, "«Начать расчёт»", async () => {
    await page.getByRole("button", { name: "Начать расчёт" }).first().click();
    await page.waitForTimeout(4000);
    await settle(page);
  });
  obs(r, "расчёт начат", { sees: `${page.url()}\n${await seen(page, "main", 3000)}` });
  await screen(page, r, "calc-started", { narrow: false });
  r.save();
};

// 1j. МУ: «Разобрать заявку» (ИИ; ветка отказа — модели на стенде без ключей), затем «Добавить строку».
scenarios["1j"] = async (browser) => {
  const r = new Report("1j");
  const page = await as(browser, r, "manager_all");
  const req = state().sc2Request || "RQ-2026-001";
  await spaGoto(page, `/erp/calc/${req}`);
  await settle(page);
  await step(page, r, "«Разобрать заявку»", async () => {
    await page.getByRole("button", { name: "Разобрать заявку" }).first().click();
    await page.waitForTimeout(2500);
  });
  const dlg = page.getByRole("dialog").last();
  obs(r, "после «Разобрать заявку»", { sees: `${page.url()}\n${await seen(page, '[role="dialog"]', 1500) || await seen(page, PANEL, 1500)}` });
  await screen(page, r, "parse-open", { narrow: false });
  const go = page.getByRole("button", { name: /^(Разобрать|Распознать|Заполнить)/ }).last();
  if (await go.isVisible().catch(() => false)) {
    await go.click();
    await page.waitForTimeout(12000);
    obs(r, "результат разбора", { sees: `${await seen(page, '[role="dialog"]', 1500) || await seen(page, PANEL, 1500)}` });
    await screen(page, r, "parse-result", { narrow: false });
  }
  await page.keyboard.press("Escape");
  await spaGoto(page, `/erp/calc/${req}`);
  await settle(page);
  await step(page, r, "«Добавить строку»", async () => {
    await page.getByRole("button", { name: "Добавить строку" }).first().click();
    await page.waitForTimeout(2500);
  });
  obs(r, "форма строки", { sees: `${page.url()}\n${await seen(page, '[role="dialog"]', 2000) || await seen(page, PANEL, 2000)}` });
  await screen(page, r, "line-form", { narrow: false });
  r.save();
};

// 1k. МУ: строка товара и строка услуги вручную — что просит таблица дальше.
scenarios["1k"] = async (browser) => {
  const r = new Report("1k");
  const page = await as(browser, r, "manager_all");
  const req = state().sc2Request || "RQ-2026-001";
  for (const [name, qty, unit, svc] of [["Рельс Р65 ГОСТ Р 51685", "40", "т", false], ["Доставка до станции Ташкент-Товарный", "1", "рейс", true]]) {
    await spaGoto(page, `/erp/calc/${req}`);
    await settle(page);
    await step(page, r, `строка «${name}»`, async () => {
      await page.getByRole("button", { name: "Добавить строку" }).first().click();
      await page.waitForTimeout(1500);
      const panel = page.locator(PANEL);
      await panel.getByLabel("Наименование").fill(name);
      await panel.getByLabel("Количество").fill(qty);
      await panel.getByLabel("Единица").fill(unit);
      if (svc) await panel.getByText("Услуга", { exact: true }).click();
      await panel.getByRole("button", { name: "Добавить", exact: true }).click();
      await page.waitForTimeout(2500);
      await settle(page);
    });
  }
  obs(r, "строки расчёта", { sees: await seen(page, "main", 3500) });
  await screen(page, r, "calc-lines", { narrow: false });
  r.save();
};

// 1l. МУ: цены, визы обеих зон, «Расчёт готов» (партнёров и каталога на стенде нет — что просит товарная строка).
scenarios["1l"] = async (browser) => {
  const r = new Report("1l");
  const page = await as(browser, r, "manager_all");
  const req = state().sc2Request || "RQ-2026-001";
  await spaGoto(page, `/erp/calc/${req}`);
  await settle(page);
  const close = page.locator(PANEL).getByRole("button", { name: /Закрыть|Свернуть/ }).last();
  if (await close.isVisible().catch(() => false)) await close.click();
  await page.waitForTimeout(800);
  const rows = page.locator("table tbody tr");
  const goods = rows.nth(0), svc = rows.nth(1);
  const fillNum = async (loc, v) => { await loc.fill(v); await loc.blur(); await page.waitForTimeout(1000); };
  const labels = async (row) => (await row.locator("input").evaluateAll((els) => els.map((e) => e.getAttribute("aria-label") || e.getAttribute("placeholder") || e.name))).join(" | ");
  obs(r, "поля строк", { sees: `товар: ${await labels(goods)}\nуслуга: ${await labels(svc)}` });
  await step(page, r, "цены товара", async () => {
    const buy = goods.getByLabel(/^Закупка|^Цена закупки/);
    if (await buy.count()) await fillNum(buy.first(), "3500");
    await fillNum(goods.getByLabel(/^Цена клиенту|^Клиенту/).first(), "4200");
  });
  await step(page, r, "цены услуги", async () => {
    await fillNum(svc.getByLabel(/^Ставка бригады/).first(), "500000");
    await fillNum(svc.getByLabel(/^Дней/).first(), "2");
    await fillNum(svc.getByLabel(/^Цена клиенту|^Клиенту/).first(), "1500000");
  });
  await settle(page);
  obs(r, "строки с ценами", { sees: await seen(page, "main", 3000) });
  await screen(page, r, "calc-priced", { narrow: false });
  for (const [row, zone] of [[goods, "снабжение"], [svc, "гл. инженер"]]) {
    await step(page, r, `виза (${zone})`, async () => {
      await row.getByRole("button", { name: /Подтвердить/ }).click();
      await page.waitForTimeout(2000);
    });
    const toast = await seen(page, ".ant-message, .ant-notification, [role=alert]", 400);
    if (toast) obs(r, `после визы (${zone})`, { sees: toast });
  }
  await settle(page);
  obs(r, "после виз", { sees: await seen(page, "main", 3000) });
  await step(page, r, "«Расчёт готов»", async () => {
    await page.getByRole("button", { name: /Расчёт готов/ }).click();
    await page.waitForTimeout(4000);
    await settle(page);
  });
  obs(r, "после «Расчёт готов»", { sees: `${page.url()}\n${await seen(page, "body", 3500)}` });
  await screen(page, r, "calc-ready", { narrow: true });
  r.save();
};

// 1m. Директор: «Задачи» → КП на одобрение → чек-лист и каналы отправки.
scenarios["1m"] = async (browser) => {
  const r = new Report("1m");
  const page = await as(browser, r, "director");
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  obs(r, "«Задачи» директора", { sees: await seen(page, "main", 1200) });
  await step(page, r, "строка «КП на одобрение» открывает КП", async () => {
    await page.getByRole("link", { name: /Открыть/ }).first().click();
    await page.waitForTimeout(3000);
    await settle(page);
  });
  obs(r, "карточка КП у директора", { sees: `${page.url()}\n${await seen(page, "main", 2500)}` });
  obs(r, "панель одобрения", { sees: await seen(page, PANEL, 3000) });
  await screen(page, r, "quote-approval", { narrow: false });
  r.save();
};

// 1n. Директор: «Одобрить КП» через «Кабинет» (почта и бот недоступны; контакт в кабинет не приглашён).
scenarios["1n"] = async (browser) => {
  const r = new Report("1n");
  const page = await as(browser, r, "director");
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  await page.getByRole("link", { name: /Открыть/ }).first().click();
  await page.waitForTimeout(3000);
  await settle(page);
  const panel = page.locator(PANEL);
  const cab = panel.getByRole("checkbox", { name: /Кабинет/ });
  obs(r, "канал «Кабинет»", { sees: `отмечен: ${await cab.isChecked().catch(() => "?")}, доступен: ${await cab.isEnabled().catch(() => "?")}` });
  if (!(await cab.isChecked().catch(() => true))) await cab.check().catch(() => {});
  await step(page, r, "«Одобрить КП»", async () => {
    await panel.getByRole("button", { name: /Одобрить КП/ }).click();
    const confirm = page.getByRole("dialog").filter({ hasText: /Одобрить|Отправить/ });
    if (await confirm.waitFor({ state: "visible", timeout: 2500 }).then(() => true).catch(() => false)) {
      obs(r, "подтверждение одобрения", { sees: await seen(page, '[role="dialog"]', 500) });
      await confirm.getByRole("button", { name: /Одобрить|Отправить/ }).last().click();
    }
    await page.waitForTimeout(6000);
    await settle(page);
  });
  obs(r, "после одобрения", { sees: `${page.url()}\n${await seen(page, "main", 1800)}` });
  obs(r, "панель после одобрения", { sees: await seen(page, PANEL, 2000) });
  await screen(page, r, "quote-approved", { narrow: true });
  r.save();
};
