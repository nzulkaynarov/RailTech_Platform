// Сценарий 6. Входящее письмо: зарегистрировать → резолюция → поручение → исполнение → ответ.
import { PANEL, Report, as, obs, seen, settle, spaGoto, step } from "./common.mjs";
export const scenarios = {};

// 6a. Делопроизводитель: «Входящие» → «Зарегистрировать входящее» — форма.
scenarios["6a"] = async (browser) => {
  const r = new Report("6a");
  const page = await as(browser, r, "registrar");
  await spaGoto(page, "/eds/inbox");
  await settle(page);
  await step(page, r, "«Зарегистрировать входящее»", async () => {
    await page.getByRole("button", { name: "Зарегистрировать входящее" }).first().click().catch(async () => page.getByRole("link", { name: "Зарегистрировать входящее" }).first().click());
    await page.waitForTimeout(2500);
    await settle(page);
  });
  obs(r, "форма регистрации", { sees: `${page.url()}\n${await seen(page, "main", 2500)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/6a-register-form-1440.png` });
  r.save();
};

// 6b. Делопроизводитель: файл → отправитель (ГНИ) → тема → срок, адресат → «Зарегистрировать».
scenarios["6b"] = async (browser) => {
  const r = new Report("6b");
  const page = await as(browser, r, "registrar");
  await spaGoto(page, "/eds/register");
  await settle(page);
  const main = page.locator("main");
  const next = async () => {
    const b = main.getByRole("button", { name: /^Далее/ }).first();
    if (await b.isVisible().catch(() => false)) { await b.click(); await page.waitForTimeout(1500); }
  };
  await step(page, r, "файл письма", async () => {
    await main.locator('input[type="file"]').first().setInputFiles(process.env.SC2_LETTER);
    await page.waitForTimeout(3000);
    await next();
  });
  obs(r, "шаг «Отправитель»", { sees: (await seen(page, "main", 3000)).split("Отправитель")[1]?.slice(0, 900) ?? "" });
  await step(page, r, "отправитель", async () => {
    const org = main.getByRole("combobox").first();
    await org.click();
    await page.keyboard.type("ГНИ");
    await page.waitForTimeout(2500);
    const opts = await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item").allInnerTexts();
    obs(r, "подсказки отправителя «ГНИ»", { sees: opts.join(" | ") || "пусто" });
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item").first().click();
    await page.waitForTimeout(1500);
    const outNo = main.getByLabel(/Исходящий номер/).first();
    if (await outNo.isVisible().catch(() => false)) await outNo.fill("01-12/345");
    await next();
  });
  await step(page, r, "тема и содержание", async () => {
    await main.getByLabel(/Тема/).first().fill("Требование о представлении пояснений по НДС");
    const body = main.getByLabel(/Суть|Содержание|Кратко/).first();
    if (await body.isVisible().catch(() => false)) await body.fill("Просят представить пояснения по декларации НДС за октябрь 2026 в течение 5 рабочих дней.");
    await next();
  });
  obs(r, "шаг «Срок, адресат и резолюция»", { sees: (await seen(page, "main", 4000)).split("Срок, адресат и резолюция")[1]?.slice(0, 1200) ?? "" });
  await next();
  obs(r, "шаг «Проверка и регистрация»", { sees: (await seen(page, "main", 4000)).split("Проверка и регистрация")[1]?.slice(0, 900) ?? "" });
  await step(page, r, "«Зарегистрировать»", async () => {
    await main.getByRole("button", { name: /^Зарегистрировать/ }).last().click();
    await page.waitForTimeout(6000);
    await settle(page);
  });
  const err = await seen(page, ".ant-message, .ant-notification, [role=alert], .ant-form-item-explain-error", 600);
  if (err) obs(r, "сообщение", { sees: err });
  obs(r, "после регистрации", { sees: `${page.url()}\n${(await seen(page, "main", 1500))}` });
  r.save();
};

// 6c. Делопроизводитель: регистрация по подписям полей (вид, способ, корреспондент ГНИ, тема) → «Зарегистрировать».
scenarios["6c"] = async (browser) => {
  const r = new Report("6c");
  const page = await as(browser, r, "registrar");
  await spaGoto(page, "/eds/register");
  await settle(page);
  const main = page.locator("main");
  const item = (label) => main.locator(".ant-form-item").filter({ has: page.locator("label", { hasText: label }) }).first();
  const pick = async (label, text, typed) => {
    await item(label).locator(".ant-select").first().click();
    if (typed) { await page.keyboard.type(typed); await page.waitForTimeout(2500); }
    await page.waitForTimeout(600);
    const opt = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option", { hasText: text }).first();
    await opt.click();
    await page.waitForTimeout(800);
  };
  const next = async () => {
    const b = main.getByRole("button", { name: /^Далее/ }).first();
    if (await b.isVisible().catch(() => false)) { await b.click(); await page.waitForTimeout(1500); }
  };
  await step(page, r, "файл", async () => {
    const f = main.locator('input[type="file"]').first();
    if (await f.count()) await f.setInputFiles(process.env.SC2_LETTER);
    await page.waitForTimeout(2500);
    await next();
  });
  await step(page, r, "отправитель", async () => {
    await pick("Вид документа", "ГНК");
    await pick("Способ получения", /./);
    await pick("Корреспондент", "ГНИ", "ГНИ");
    await item("Исходящий номер отправителя").locator("input").fill("01-12/345");
    await next();
  });
  await step(page, r, "тема", async () => {
    await item("Тема").locator("input, textarea").first().fill("Требование о представлении пояснений по НДС");
    await next();
  });
  await step(page, r, "срок и адресат", async () => {
    await next();
  });
  obs(r, "проверка перед регистрацией", { sees: (await seen(page, "main", 4000)).split("Проверка и регистрация")[1]?.slice(0, 900) ?? "" });
  await step(page, r, "«Зарегистрировать»", async () => {
    await main.getByRole("button", { name: /^Зарегистрировать/ }).last().click();
    await page.waitForTimeout(6000);
    await settle(page);
  });
  const err = await seen(page, ".ant-message, .ant-notification, .ant-form-item-explain-error", 600);
  if (err) obs(r, "сообщение", { sees: err });
  obs(r, "после регистрации", { sees: `${page.url()}\n${(await seen(page, "main", 1200))}` });
  r.save();
};

// 6d. Делопроизводитель: дозаполнить сохранённый черновик регистрации (тема) → «Зарегистрировать»; ошибки — как есть.
scenarios["6d"] = async (browser) => {
  const r = new Report("6d");
  const page = await as(browser, r, "registrar");
  await spaGoto(page, "/eds/register");
  await settle(page);
  const main = page.locator("main");
  const topic = main.getByRole("textbox", { name: "Тема", exact: true });
  if (await topic.isVisible().catch(() => false)) await topic.fill("Требование о представлении пояснений по НДС");
  for (let i = 0; i < 3; i++) {
    const b = main.getByRole("button", { name: /^Далее/ }).first();
    if (!(await b.isVisible().catch(() => false))) break;
    await b.click();
    await page.waitForTimeout(1500);
  }
  const all = await seen(page, "main", 6000);
  obs(r, "форма перед регистрацией", { sees: all.slice(all.indexOf("Файл письма")) });
  const reg = main.getByRole("button", { name: /^Зарегистрировать/ }).last();
  obs(r, "кнопка", { sees: `видна: ${await reg.isVisible().catch(() => false)}` });
  if (await reg.isVisible().catch(() => false)) {
    await reg.click();
    await page.waitForTimeout(6000);
    await settle(page);
    const err = await seen(page, ".ant-message, .ant-notification, .ant-form-item-explain-error", 600);
    if (err) obs(r, "сообщение", { sees: err });
    obs(r, "после «Зарегистрировать»", { sees: `${page.url()}\n${(await seen(page, "main", 1500))}` });
  }
  await page.screenshot({ path: `${process.env.QA_SHOTS}/6d-register-1440.png` });
  r.save();
};

// 6e. Делопроизводитель: какие кнопки есть на сохранённом черновике регистрации (поиск пути дальше шага 4).
scenarios["6e"] = async (browser) => {
  const r = new Report("6e");
  const page = await as(browser, r, "registrar");
  await spaGoto(page, "/eds/register");
  await settle(page);
  const buttons = await page.locator("button:visible, a[role=button]:visible").evaluateAll((els) =>
    els.map((e) => `${e.innerText.trim().replace(/\s+/g, " ")}${e.disabled ? " [disabled]" : ""}`).filter(Boolean),
  );
  obs(r, "кнопки на странице", { sees: buttons.join(" | ") });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/6e-register-1440.png` });
  r.save();
};

// 6f. Делопроизводитель: письмо ГНИ — файл, вид, способ, корреспондент (завести из подсказок), тема → «Зарегистрировать».
scenarios["6f"] = async (browser) => {
  const r = new Report("6f");
  const page = await as(browser, r, "registrar");
  await spaGoto(page, "/eds/register");
  await settle(page);
  const main = page.locator("main");
  const dropdown = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option");
  const errors = async () => (await page.locator(".ant-form-item-explain-error:visible, .ant-message:visible").allInnerTexts()).join(" | ");
  const go = async (name) => {
    await main.getByRole("button", { name: new RegExp(`^Далее: ${name}`) }).first().click();
    await page.waitForTimeout(1800);
    const e = await errors();
    if (e) obs(r, `после «Далее: ${name}» — сообщения`, { sees: e });
  };
  const choose = async (label, text) => {
    await main.getByLabel(label, { exact: true }).click({ force: true });
    await page.waitForTimeout(700);
    obs(r, `варианты «${label}»`, { sees: (await dropdown.allInnerTexts()).join(" | ") });
    await dropdown.filter({ hasText: text }).first().click();
    await page.waitForTimeout(500);
  };
  await step(page, r, "файл письма ГНИ", async () => {
    const drop = main.getByRole("button", { name: "Убрать" }).first();
    if (await drop.isVisible().catch(() => false)) { await drop.click(); await page.waitForTimeout(800); }
    await main.locator('input[type="file"]').first().setInputFiles(process.env.SC2_TAX);
    await page.waitForTimeout(3500);
  });
  await go("Отправитель");
  await step(page, r, "вид и способ получения", async () => {
    await choose("Вид документа", "ГНК");
    await choose("Способ получения", /./);
  });
  await step(page, r, "корреспондент — ГНИ Юнусабадского района", async () => {
    const sender = main.getByLabel("Корреспондент (организация)");
    await sender.click();
    await sender.fill("ГНИ Юнусабадского района");
    await page.waitForTimeout(2500);
    const opts = await dropdown.allInnerTexts();
    obs(r, "подсказки корреспондента", { sees: opts.join(" | ") || "пусто" });
    const add = dropdown.filter({ hasText: /Завести организацию/ }).first();
    await add.click();
    const sheet = page.getByRole("dialog", { name: "Новая организация" });
    await sheet.waitFor({ timeout: 8000 });
    obs(r, "окно «Новая организация»", { sees: await seen(page, '[role="dialog"]', 1200) });
    await page.screenshot({ path: `${process.env.QA_SHOTS}/6f-new-org-1440.png` });
    await sheet.getByRole("button", { name: "Завести" }).click();
    await sheet.waitFor({ state: "detached", timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(1200);
    const e = await errors();
    if (e) obs(r, "после «Завести»", { sees: e });
  });
  await step(page, r, "исходящий номер отправителя", async () => {
    await main.getByLabel("Исходящий номер отправителя").fill("01-12/345");
  });
  obs(r, "шаг 2 заполнен", { sees: (await seen(page, "main", 5000)).split("Отправитель")[1]?.slice(0, 900) ?? "" });
  await go("Тема");
  await step(page, r, "тема", async () => {
    const topic = main.getByRole("textbox", { name: "Тема", exact: true });
    await topic.fill("Требование о представлении пояснений по НДС за октябрь");
  });
  obs(r, "шаг 3 «Тема и содержание»", { sees: (await seen(page, "main", 6000)).split("Тема и содержание")[1]?.slice(0, 900) ?? "" });
  await go("Срок");
  obs(r, "шаг 4 «Срок, адресат и резолюция»", { sees: (await seen(page, "main", 6000)).split("Срок, адресат и резолюция")[1]?.slice(0, 1400) ?? "" });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/6f-step4-1440.png` });
  await go("Проверка");
  obs(r, "шаг 5 «Проверка и регистрация»", { sees: (await seen(page, "main", 6000)).split("Проверка и регистрация")[1]?.slice(0, 1400) ?? "" });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/6f-check-1440.png` });
  await step(page, r, "«Зарегистрировать»", async () => {
    await main.getByRole("button", { name: /^Зарегистрировать/ }).last().click();
    await page.waitForTimeout(6000);
    await settle(page);
  });
  const e = await errors();
  if (e) obs(r, "сообщения после регистрации", { sees: e });
  obs(r, "после регистрации", { sees: `${page.url()}\n${await seen(page, "main", 1800)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/6f-registered-1440.png` });
  r.save();
};

// 6g. Директор: «Главная» → письмо IN-002/26 → резолюция «Подготовить ответ», бухгалтеру, срок → «Наложить резолюцию».
scenarios["6g"] = async (browser) => {
  const r = new Report("6g");
  const page = await as(browser, r, "director");
  await settle(page);
  obs(r, "«Главная» директора", { sees: `${page.url()}\n${await seen(page, "main", 1500)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/6g-home-1440.png` });
  const row = page.locator("main li, main [role=listitem], main .ant-list-item, main tr, main a").filter({ hasText: "IN-002/26" }).last();
  obs(r, "строка задачи", { sees: (await row.innerText().catch(() => "нет")).replace(/\n/g, " · ") });
  const open = row.getByRole("button").or(row.getByRole("link")).first();
  if (await open.isVisible().catch(() => false)) {
    await step(page, r, "открыть задачу с «Главной»", async () => { await open.click(); await page.waitForTimeout(2500); await settle(page); });
  }
  if (!/eds\/inbox/.test(page.url())) {
    obs(r, "с «Главной» не открылось", { sees: page.url() });
    await spaGoto(page, "/eds/inbox?letter=IN-002%2F26&tab=resolution&panel=open");
    await settle(page);
  }
  obs(r, "открыто", { sees: `${page.url()}\n${(await seen(page, PANEL, 2500)) || (await seen(page, "main", 2500))}` });
  const scope = (await page.locator(PANEL).isVisible().catch(() => false)) ? page.locator(PANEL) : page.locator("main");
  const tab = scope.getByRole("tab", { name: "Резолюция" });
  if (await tab.isVisible().catch(() => false)) { await tab.click(); await page.waitForTimeout(1200); }
  const dropdown = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option");
  await step(page, r, "тип «Подготовить ответ»", async () => {
    await scope.getByRole("radio", { name: /Подготовить ответ/ }).check({ force: true });
    await page.waitForTimeout(600);
  });
  await step(page, r, "ответственный — бухгалтер", async () => {
    await scope.getByLabel("Ответственный", { exact: true }).click({ force: true });
    await page.keyboard.type("Бухгалт");
    await page.waitForTimeout(1500);
    obs(r, "варианты «Ответственный»", { sees: (await dropdown.allInnerTexts()).join(" | ") });
    await dropdown.first().click();
    await page.waitForTimeout(600);
  });
  const due = scope.getByLabel("Срок исполнения", { exact: true });
  obs(r, "срок исполнения до ввода", { sees: `значение: «${await due.inputValue().catch(() => "?")}»; ${await seen(page, `${PANEL} .ant-form-item:has(label:text-is("Срок исполнения"))`, 300)}` });
  if (!(await due.inputValue().catch(() => ""))) {
    await step(page, r, "срок 26.11.2026", async () => {
      await due.click();
      await page.keyboard.type("26.11.2026");
      await page.keyboard.press("Enter");
      await page.waitForTimeout(600);
    });
  }
  obs(r, "форма резолюции перед отправкой", { sees: (await seen(page, PANEL, 4000)).split("Тип резолюции")[1]?.slice(0, 1500) ?? "" });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/6g-resolution-1440.png` });
  await step(page, r, "«Наложить резолюцию»", async () => {
    await scope.getByRole("button", { name: "Наложить резолюцию" }).click();
    await page.waitForTimeout(4000);
    await settle(page);
  });
  const e = (await page.locator(".ant-form-item-explain-error:visible, .ant-message:visible").allInnerTexts()).join(" | ");
  if (e) obs(r, "сообщения", { sees: e });
  obs(r, "после резолюции", { sees: `${page.url()}\n${(await seen(page, PANEL, 1800)) || (await seen(page, "main", 1800))}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/6g-after-1440.png` });
  r.save();
};

/** Видимые кнопки и ссылки-кнопки области (для поиска пути дальше). */
async function buttonsOf(page, selector = "body") {
  return page.locator(`${selector} button:visible, ${selector} a[role=button]:visible, ${selector} a.ant-btn:visible`).evaluateAll((els) =>
    [...new Set(els.map((e) => `${e.innerText.trim().replace(/\s+/g, " ")}${e.disabled ? " [disabled]" : ""}`).filter(Boolean))],
  );
}

/** Поля формы: подпись → значение (input, textarea, выбранное в select). */
async function formState(page, selector = "main") {
  return page.locator(`${selector} .ant-form-item`).evaluateAll((items) =>
    items.map((it) => {
      const label = it.querySelector("label")?.innerText.trim() ?? "?";
      const input = it.querySelector("input:not([type=hidden]):not([type=file]), textarea");
      const sel = it.querySelector(".ant-select-selection-item, .ant-select-selection-overflow");
      const value = sel?.innerText.trim() || input?.value || "";
      return `${label}: «${value}»`;
    }).filter((x) => !x.startsWith("?")),
  );
}

// 6h. Бухгалтер: «Главная» → поручение по IN-002/26 → «Подготовить ответ» — что подставлено в исходящее.
scenarios["6h"] = async (browser) => {
  const r = new Report("6h");
  const page = await as(browser, r, "accountant");
  await settle(page);
  obs(r, "«Главная» бухгалтера", { sees: `${page.url()}\n${await seen(page, "main", 1500)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/6h-home-1440.png` });
  const row = page.locator("main li, main [role=listitem], main .ant-list-item, main tr, main a").filter({ hasText: "IN-002/26" }).last();
  obs(r, "строка задачи", { sees: (await row.innerText().catch(() => "нет")).replace(/\n/g, " · ") });
  const open = row.getByRole("button").or(row.getByRole("link")).first();
  if (await open.isVisible().catch(() => false)) {
    await step(page, r, "«Открыть» поручение", async () => { await open.click(); await page.waitForTimeout(2500); await settle(page); });
  }
  obs(r, "экран поручения", { sees: `${page.url()}\n${await seen(page, "main", 2500)}` });
  obs(r, "кнопки", { sees: (await buttonsOf(page, "main")).join(" | ") });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/6h-task-1440.png` });
  const reply = page.getByRole("button", { name: /Подготовить ответ|Ответить|Написать ответ|Ответ/ }).or(page.getByRole("link", { name: /Подготовить ответ|Ответить|Написать ответ/ })).first();
  if (await reply.isVisible().catch(() => false)) {
    await step(page, r, "«Подготовить ответ»", async () => { await reply.click(); await page.waitForTimeout(3000); await settle(page); });
    obs(r, "форма ответа", { sees: `${page.url()}\n${await seen(page, "main", 2500)}` });
    obs(r, "поля формы", { sees: (await formState(page)).join(" | ") });
    await page.screenshot({ path: `${process.env.QA_SHOTS}/6h-reply-form-1440.png` });
  }
  r.save();
};

// 6i. Бухгалтер: ответ на IN-002/26 — кому, почта, текст → «Передать на регистрацию».
scenarios["6i"] = async (browser) => {
  const r = new Report("6i");
  const page = await as(browser, r, "accountant");
  await settle(page);
  // Путь «Главная» → «Открыть» → «Ответить» пройден в 6h; здесь — сразу форма ответа на поручение.
  await spaGoto(page, "/eds/new?type=letter&reply_to=IN-002%2F26&reply_id=b8840cbe-1096-4223-9dff-be7f3d434c62");
  await page.waitForTimeout(2500);
  await settle(page);
  const main = page.locator("main");
  await step(page, r, "кому и почта", async () => {
    await main.getByLabel("Почта адресата").fill("gni.yunusabad@demo.example");
    await main.getByLabel("Кому (должность и ФИО)").fill("Начальнику ГНИ Юнусабадского района Каримову А.");
    await main.getByRole("button", { name: "Далее: Текст и вложения" }).click();
    await page.waitForTimeout(1500);
  });
  obs(r, "шаг «Текст и вложения»", { sees: (await seen(page, "main", 5000)).split("Текст и вложения")[1]?.slice(0, 900) ?? "" });
  await step(page, r, "текст письма", async () => {
    const editor = main.locator("[contenteditable=true]").first();
    await editor.click();
    await page.keyboard.press("Control+A");
    await page.keyboard.type("На ваше требование № 01-12/345 от 18.11.2026 сообщаем: расхождения в декларации по НДС за октябрь 2026 года вызваны счётом-фактурой поставщика, полученным после сдачи декларации. Уточнённая декларация будет представлена до 25.11.2026.");
    await page.waitForTimeout(800);
  });
  for (let i = 0; i < 3; i++) {
    const next = main.getByRole("button", { name: /^Далее/ }).first();
    if (!(await next.isVisible().catch(() => false))) break;
    obs(r, `кнопка «${(await next.innerText()).trim()}»`, {});
    await next.click();
    await page.waitForTimeout(1500);
  }
  obs(r, "перед отправкой", { sees: (await buttonsOf(page, "main")).join(" | ") });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/6i-before-send-1440.png` });
  await step(page, r, "«Передать на регистрацию»", async () => {
    await main.getByRole("button", { name: "Передать на регистрацию" }).click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) { obs(r, "окно", { sees: await seen(page, '[role="dialog"]', 600) }); await dlg.getByRole("button").last().click(); }
    await page.waitForTimeout(3500);
    await settle(page);
  });
  const e = (await page.locator(".ant-form-item-explain-error:visible, .ant-message:visible, [role=alert]:visible").allInnerTexts()).join(" | ");
  if (e) obs(r, "сообщения", { sees: e });
  obs(r, "после передачи", { sees: `${page.url()}\n${await seen(page, "main", 1800)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/6i-after-1440.png` });
  r.save();
};

// 6j. Делопроизводитель: задача по ответу → карточка — что предлагается (без нажатия «Подписать»: отказ проверен в 5).
scenarios["6j"] = async (browser) => {
  const r = new Report("6j");
  const page = await as(browser, r, "registrar");
  await settle(page);
  obs(r, "«Главная» делопроизводителя", { sees: `${page.url()}\n${await seen(page, "main", 1600)}` });
  const row = page.locator("main li, main [role=listitem], main .ant-list-item, main tr").filter({ hasText: /На IN-002\/26/ }).last();
  obs(r, "строка задачи", { sees: (await row.innerText().catch(() => "нет")).replace(/\n/g, " · ") });
  const open = row.getByRole("button").or(row.getByRole("link")).first();
  if (await open.isVisible().catch(() => false)) {
    await step(page, r, "«Открыть»", async () => { await open.click(); await page.waitForTimeout(2500); await settle(page); });
  }
  obs(r, "карточка", { sees: `${page.url()}\n${(await seen(page, PANEL, 2000)) || (await seen(page, "main", 2000))}` });
  obs(r, "кнопки", { sees: (await buttonsOf(page, "body")).join(" | ") });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/6j-card-1440.png` });
  r.save();
};

// 6k. Директор: задача «Подписать» по ответу → «Подписать» → номер, отправка; поручение и входящее после регистрации.
scenarios["6k"] = async (browser) => {
  const r = new Report("6k");
  const page = await as(browser, r, "director");
  await settle(page);
  obs(r, "«Главная» директора", { sees: `${page.url()}\n${await seen(page, "main", 1600)}` });
  const row = page.locator("main li, main [role=listitem], main .ant-list-item, main tr").filter({ hasText: /На IN-002\/26/ }).last();
  obs(r, "строка задачи", { sees: (await row.innerText().catch(() => "нет")).replace(/\n/g, " · ") });
  const open = row.getByRole("button").or(row.getByRole("link")).first();
  if (await open.isVisible().catch(() => false)) {
    await step(page, r, "«Открыть»", async () => { await open.click(); await page.waitForTimeout(2500); await settle(page); });
  } else {
    await spaGoto(page, "/eds/documents?box=outgoing&scope=all&doc=cef1909d-de6d-4833-b01f-bc10e3f9c4f8&panel=open");
    await settle(page);
  }
  obs(r, "карточка", { sees: `${page.url()}\n${(await seen(page, PANEL, 1500)) || (await seen(page, "main", 1500))}` });
  obs(r, "кнопки", { sees: (await buttonsOf(page, "body")).join(" | ") });
  const sign = page.getByRole("button", { name: /^Подписать/ }).first();
  await step(page, r, "«Подписать»", async () => {
    await sign.click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) {
      obs(r, "окно подписи", { sees: await seen(page, '[role="dialog"]', 1200) });
      await page.screenshot({ path: `${process.env.QA_SHOTS}/6k-sign-dialog-1440.png` });
      await dlg.getByRole("button", { name: /Подписать/ }).last().click();
    }
    await page.waitForTimeout(6000);
    await settle(page);
  });
  const e = (await page.locator(".ant-message:visible, [role=alert]:visible").allInnerTexts()).join(" | ");
  if (e) obs(r, "сообщения", { sees: e });
  obs(r, "после подписи", { sees: `${page.url()}\n${(await seen(page, PANEL, 2000)) || (await seen(page, "main", 2000))}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/6k-signed-1440.png` });
  await spaGoto(page, "/eds/inbox/IN-002%2F26");
  await settle(page);
  obs(r, "входящее IN-002/26 после ответа", { sees: await seen(page, "main", 2500) });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/6k-incoming-1440.png` });
  r.save();
};
