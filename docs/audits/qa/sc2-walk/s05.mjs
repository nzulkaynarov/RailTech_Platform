// Сценарий 5. Исходящее письмо: написать → согласовать → подписать → зарегистрировать → отправить → ответ.
import { PANEL, Report, as, obs, seen, settle, spaGoto, step } from "./common.mjs";
import { mailbox, mailText } from "./s02.mjs";
export const scenarios = {};

// 5a. Менеджер: «Создать → Исходящее письмо» — форма и шаги.
scenarios["5a"] = async (browser) => {
  const r = new Report("5a");
  const page = await as(browser, r, "manager_all");
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  await page.getByRole("button", { name: "Создать" }).first().click();
  await page.waitForTimeout(800);
  await page.getByText("Исходящее письмо", { exact: true }).first().click();
  await page.waitForTimeout(3000);
  await settle(page);
  obs(r, "форма исходящего", { sees: `${page.url()}\n${await seen(page, "main", 3000)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/5a-letter-form-1440.png`, fullPage: false });
  r.save();
};

// 5b. Менеджер: тема, адресат из контрагентов, человек, текст → шаги → «Отправить» делопроизводителю.
scenarios["5b"] = async (browser) => {
  const r = new Report("5b");
  const page = await as(browser, r, "manager_all");
  await spaGoto(page, "/eds/new?type=letter");
  await settle(page);
  const main = page.locator("main");
  await step(page, r, "о чём и кому", async () => {
    await main.getByLabel("Тема").fill("О графике поставки по проекту PRJ-2026-001");
    const org = main.getByLabel("Адресат (организация)");
    await org.click();
    await page.keyboard.type("Сценарий");
    await page.waitForTimeout(2000);
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option", { hasText: "Сценарий Путь" }).first().click();
    await page.waitForTimeout(1500);
    const person = main.getByLabel("Кому — человек");
    await person.click();
    await page.waitForTimeout(1200);
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option").first().click().catch(() => {});
    await page.waitForTimeout(800);
  });
  obs(r, "после выбора адресата", { sees: (await seen(page, "main", 2500)).slice(0, 1400) });
  await step(page, r, "«Далее: Текст и вложения»", async () => {
    await main.getByRole("button", { name: "Далее: Текст и вложения" }).click();
    await page.waitForTimeout(2000);
  });
  await step(page, r, "текст письма", async () => {
    const editor = main.locator("[contenteditable=true]").first();
    await editor.click();
    await page.keyboard.type("Сообщаем, что поставка рельсов Р65 по проекту PRJ-2026-001 выполнена 19.11.2026. Просим подтвердить получение.");
    await page.waitForTimeout(800);
  });
  for (let i = 0; i < 3; i++) {
    const next = main.getByRole("button", { name: /^Далее/ }).first();
    if (!(await next.isVisible().catch(() => false))) break;
    await next.click();
    await page.waitForTimeout(1500);
  }
  obs(r, "шаг «Проверка и отправка»", { sees: (await seen(page, "main", 4000)).split("Проверка и отправка")[1]?.slice(0, 1500) ?? "" });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/5b-letter-review-1440.png` });
  const send = main.getByRole("button", { name: /^(Отправить|На регистрацию|Передать)/ }).last();
  obs(r, "кнопка отправки", { sees: `${await send.innerText().catch(() => "нет")}, активна: ${await send.isEnabled().catch(() => false)}` });
  if (await send.isEnabled().catch(() => false)) {
    await step(page, r, "отправка на регистрацию", async () => {
      await send.click();
      await page.waitForTimeout(1500);
      const dlg = page.getByRole("dialog");
      if (await dlg.isVisible().catch(() => false)) { obs(r, "окно", { sees: await seen(page, '[role="dialog"]', 600) }); await dlg.getByRole("button").last().click(); }
      await page.waitForTimeout(5000);
      await settle(page);
    });
    obs(r, "после отправки", { sees: `${page.url()}\n${(await seen(page, "main", 1500))}` });
  }
  r.save();
};

// 5c. Подсказки «Адресат (организация)» по разным запросам.
scenarios["5c"] = async (browser) => {
  const r = new Report("5c");
  const page = await as(browser, r, "manager_all");
  for (const q of ["Сценарий", "ООО", "3012", "Демо"]) {
    await spaGoto(page, "/eds/new?type=letter");
    await settle(page);
    const org = page.locator("main").getByLabel("Адресат (организация)");
    await org.click();
    await page.keyboard.type(q);
    await page.waitForTimeout(3000);
    const opts = await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item").allInnerTexts();
    obs(r, `подсказки по «${q}»`, { sees: opts.join(" | ") || "пусто" });
  }
  await page.screenshot({ path: `${process.env.QA_SHOTS}/5c-addressee-1440.png` });
  r.save();
};

// 5d. Менеджер: письмо в ГНИ — «+ Завести организацию», почта адресата, текст → «Передать на регистрацию».
scenarios["5d"] = async (browser) => {
  const r = new Report("5d");
  const page = await as(browser, r, "manager_all");
  await spaGoto(page, "/eds/new?type=letter");
  await settle(page);
  const main = page.locator("main");
  await step(page, r, "о чём и кому", async () => {
    await main.getByLabel("Тема").fill("О сверке расчётов за ноябрь 2026");
    const org = main.getByLabel("Адресат (организация)");
    await org.click();
    await page.keyboard.press("Control+A");
    await page.keyboard.press("Backspace");
    await page.keyboard.type("ГНИ Мирабадского района");
    await page.waitForTimeout(2500);
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item", { hasText: "Завести организацию" }).first().click();
    await page.waitForTimeout(2000);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) {
      obs(r, "окно новой организации", { sees: await seen(page, '[role="dialog"]', 800) });
      await dlg.getByRole("button", { name: /Сохранить|Завести|Создать|Добавить/ }).last().click();
      await page.waitForTimeout(2500);
    }
    await main.getByLabel("Почта адресата").fill("gni.sc2@demo.example");
    await main.getByLabel("Кому (должность и ФИО)").fill("Начальнику ГНИ Мирабадского района Каримову А. А.");
    await main.getByRole("button", { name: "Далее: Текст и вложения" }).click();
    await page.waitForTimeout(1500);
  });
  await step(page, r, "текст письма", async () => {
    const editor = main.locator("[contenteditable=true]").first();
    await editor.click();
    await page.keyboard.press("Control+A");
    await page.keyboard.type("Просим провести сверку расчётов по налогу на добавленную стоимость за ноябрь 2026 года.");
    await page.waitForTimeout(800);
  });
  for (let i = 0; i < 3; i++) {
    const next = main.getByRole("button", { name: /^Далее/ }).first();
    if (!(await next.isVisible().catch(() => false))) break;
    await next.click();
    await page.waitForTimeout(1500);
  }
  await step(page, r, "«Передать на регистрацию»", async () => {
    await main.getByRole("button", { name: "Передать на регистрацию" }).click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) { obs(r, "окно", { sees: await seen(page, '[role="dialog"]', 600) }); await dlg.getByRole("button").last().click(); }
    await page.waitForTimeout(5000);
    await settle(page);
  });
  obs(r, "после передачи", { sees: `${page.url()}\n${(await seen(page, "main", 1500))}` });
  r.save();
};

// 5e. Делопроизводитель: «Задачи» и «Исходящие» — дошло ли письмо на регистрацию; менеджер: карточка черновика.
scenarios["5e"] = async (browser) => {
  const r = new Report("5e");
  const page = await as(browser, r, "registrar");
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  const q = await seen(page, "main", 1600);
  obs(r, "«Задачи» делопроизводителя", { sees: q.slice(q.indexOf("Что сделать сейчас")) });
  await spaGoto(page, "/eds/documents?box=outgoing&scope=all");
  await settle(page);
  obs(r, "«Исходящие · Все» у делопроизводителя", { sees: (await seen(page, "main", 1400)) });
  await page.close();
  const pm = await as(browser, r, "manager_all");
  await spaGoto(pm, "/eds/documents?box=outgoing&scope=mine");
  await settle(pm);
  await pm.getByText("О сверке расчётов за ноябрь 2026").first().click();
  await pm.waitForTimeout(2500);
  obs(r, "карточка черновика у менеджера", { sees: await seen(pm, PANEL, 1800) });
  r.save();
};

// 5f. Делопроизводитель: строка «Зарегистрировать ИСХ» → регистрация → письмо адресату (Mailpit), имя PDF.
scenarios["5f"] = async (browser) => {
  const r = new Report("5f");
  const page = await as(browser, r, "registrar");
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  await page.getByRole("link", { name: /Открыть/ }).first().click();
  await page.waitForTimeout(3000);
  await settle(page);
  obs(r, "письмо у делопроизводителя", { sees: `${page.url()}\n${await seen(page, PANEL, 1800)}` });
  const before = mailbox().length;
  const reg = page.getByRole("button", { name: /Зарегистрировать/ }).first();
  obs(r, "кнопка регистрации", { sees: `${await reg.innerText().catch(() => "нет")}, активна: ${await reg.isEnabled().catch(() => false)}` });
  await step(page, r, "регистрация", async () => {
    await reg.click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) { obs(r, "окно регистрации", { sees: await seen(page, '[role="dialog"]', 900) }); await dlg.getByRole("button").last().click(); }
    await page.waitForTimeout(8000);
    await settle(page);
  });
  obs(r, "после регистрации", { sees: await seen(page, PANEL, 1800) });
  for (const m of mailbox().slice(0, Math.max(0, mailbox().length - before))) {
    const t = mailText(m.ID);
    obs(r, `письмо «${t.subject}»`, { sees: `кому: ${m.To.map((x) => x.Address).join(", ")}; вложения: ${t.attachments.join(", ") || "—"}\n${t.text.slice(0, 500)}` });
  }
  r.save();
};

// 5g. Делопроизводитель: «Подписать» в карточке письма — что это за шаг и ведёт ли к регистрации.
scenarios["5g"] = async (browser) => {
  const r = new Report("5g");
  const page = await as(browser, r, "registrar");
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  await page.getByRole("link", { name: /Открыть/ }).first().click();
  await page.waitForTimeout(3000);
  await settle(page);
  const before = mailbox().length;
  await step(page, r, "«Подписать»", async () => {
    await page.locator(PANEL).getByRole("button", { name: "Подписать" }).first().click();
    await page.waitForTimeout(2000);
  });
  obs(r, "после «Подписать»", { sees: `${page.url()}\n${await seen(page, '[role="dialog"]', 1200) || await seen(page, PANEL, 1500)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/5g-sign-1440.png` });
  const dlg = page.getByRole("dialog");
  if (await dlg.isVisible().catch(() => false)) {
    const go = dlg.getByRole("button", { name: /Подписать|Зарегистрировать|Отправить/ }).last();
    if (await go.isEnabled().catch(() => false)) {
      await go.click();
      await page.waitForTimeout(8000);
      await settle(page);
      obs(r, "после подтверждения подписи", { sees: await seen(page, PANEL, 1500) });
    } else obs(r, "кнопка в окне неактивна", { sees: await seen(page, '[role="dialog"]', 900) });
  }
  for (const m of mailbox().slice(0, Math.max(0, mailbox().length - before))) {
    const t = mailText(m.ID);
    obs(r, `письмо «${t.subject}»`, { sees: `кому: ${m.To.map((x) => x.Address).join(", ")}; вложения: ${t.attachments.join(", ") || "—"}` });
  }
  r.save();
};

// 5h. Директор: видит ли письмо (задачи, исходящие) и может ли «Подписать» с отправкой на почту.
scenarios["5h"] = async (browser) => {
  const r = new Report("5h");
  const page = await as(browser, r, "director");
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  const q = await seen(page, "main", 1500);
  obs(r, "«Задачи» директора", { sees: q.slice(q.indexOf("Что сделать сейчас")) });
  await spaGoto(page, "/eds/documents?box=outgoing&scope=all");
  await settle(page);
  await page.getByText("О сверке расчётов за ноябрь 2026").first().click();
  await page.waitForTimeout(2500);
  const before = mailbox().length;
  await step(page, r, "директор: «Подписать» → по почте сразу", async () => {
    await page.locator(PANEL).getByRole("button", { name: "Подписать" }).first().click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    const mail = dlg.getByLabel(/Отправить адресату на почту/);
    if (await mail.count() && !(await mail.isChecked().catch(() => true))) await mail.check();
    await dlg.getByRole("button", { name: "Подписать письмо" }).click();
    await page.waitForTimeout(8000);
    await settle(page);
  });
  obs(r, "после подписи директором", { sees: await seen(page, PANEL, 1500) });
  for (const m of mailbox().slice(0, Math.max(0, mailbox().length - before))) {
    const t = mailText(m.ID);
    obs(r, `письмо «${t.subject}»`, { sees: `кому: ${m.To.map((x) => x.Address).join(", ")}; вложения: ${t.attachments.join(", ") || "—"}\n${t.text.slice(0, 300)}` });
  }
  r.save();
};
