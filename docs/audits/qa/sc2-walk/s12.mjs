// Сценарий 12. Первая установка → реквизиты → почта → бот → готовность (шаги после мастера).
import { PANEL, Report, as, obs, screen, seen, settle, spaGoto, step, state } from "./common.mjs";
export const scenarios = {};

// 12a. Администратор: «Настройки · Подключения · Почта» — что просит форма.
scenarios["12a"] = async (browser) => {
  const r = new Report("12a");
  const page = await as(browser, r, "admin");
  await spaGoto(page, "/admin/integrations");
  await settle(page);
  obs(r, "Подключения", { sees: `${page.url()}\n${await seen(page, "main", 2000)}` });
  await screen(page, r, "connections", { narrow: false });
  await spaGoto(page, "/admin/mail");
  await settle(page);
  obs(r, "Почта", { sees: `${page.url()}\n${await seen(page, "main", 2500)}` });
  await screen(page, r, "mail", { narrow: false });
  r.save();
};

// 12b. Администратор: «Настроить SMTP» → Mailpit стенда (rt-scen-mailpit:1025, без шифрования и пароля).
scenarios["12b"] = async (browser) => {
  const r = new Report("12b");
  const page = await as(browser, r, "admin");
  await spaGoto(page, "/admin/mail");
  await settle(page);
  await step(page, r, "«Настроить SMTP»", async () => {
    await page.getByRole("button", { name: "Настроить SMTP" }).click();
    await page.waitForTimeout(1500);
  });
  const form = page.locator(PANEL);
  const fields = await form.locator("input, select, [role=combobox], [role=radio]").evaluateAll((els) => els.map((e) => `${e.getAttribute("aria-label") || e.getAttribute("name") || e.id}:${e.getAttribute("type") || e.getAttribute("role") || e.tagName}`));
  obs(r, "форма SMTP", { sees: `${await seen(page, PANEL, 2000)}\nполя: ${fields.join(" | ")}` });
  await screen(page, r, "smtp-form", { narrow: false });
  r.save();
};

// 12c. Администратор: SMTP → Mailpit, «Сохранить», «Проверить связь», «Проверить отправку».
scenarios["12c"] = async (browser) => {
  const r = new Report("12c");
  const page = await as(browser, r, "admin");
  await spaGoto(page, "/admin/mail");
  await settle(page);
  await page.getByRole("button", { name: "Настроить SMTP" }).click();
  await page.waitForTimeout(1000);
  const main = page.locator("main");
  await step(page, r, "форма заполнена", async () => {
    await main.getByLabel("Сервер (хост)").fill("rt-scen-mailpit");
    await main.getByLabel("Порт").fill("1025");
    await main.locator(".ant-select").filter({ hasText: "STARTTLS" }).first().click();
    const opts = await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option").allInnerTexts();
    obs(r, "варианты шифрования", { sees: opts.join(" | ") });
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option", { hasText: /Нет|Без/ }).first().click();
    await main.getByLabel("Адрес отправителя").fill("noreply@demo.example");
    await main.getByLabel("Имя отправителя").fill("Демо Рельс");
    const st = state();
    await main.getByLabel("Ваш пароль администратора").fill(st.passwords?.[st.adminEmail] ?? st.adminPw);
  });
  const rest = await seen(page, "main", 6000);
  obs(r, "форма после заполнения", { sees: rest.slice(rest.indexOf("Сервер (хост)"), rest.indexOf("Приём: общий ящик")) });
  await screen(page, r, "smtp-filled", { narrow: false });
  await step(page, r, "«Сохранить»", async () => {
    await main.getByRole("button", { name: "Сохранить настройки" }).first().click();
    await page.waitForTimeout(3000);
    await settle(page);
  });
  const after = await seen(page, "main", 6000);
  obs(r, "после сохранения", { sees: after.slice(after.indexOf("Состояние"), after.indexOf("Приём: общий ящик")) });
  for (const name of ["Проверить связь", "Проверить отправку"]) {
    await step(page, r, `«${name}»`, async () => {
      await main.getByRole("button", { name }).first().click();
      await page.waitForTimeout(5000);
    });
    const dlg = await seen(page, '[role="dialog"]', 600);
    obs(r, `после «${name}»`, { sees: dlg || (await seen(page, ".ant-message, .ant-notification, [role=alert], [role=status]", 600)) });
    if (dlg) {
      const to = page.getByRole("dialog").getByLabel(/Кому|Адрес/);
      if (await to.count()) {
        await to.first().fill("admin.check@demo.example");
        await page.getByRole("dialog").getByRole("button", { name: /Отправить|Проверить/ }).last().click();
        await page.waitForTimeout(5000);
        obs(r, "итог проверки отправки", { sees: await seen(page, '[role="dialog"], .ant-message, [role=alert]', 600) });
      }
      await page.keyboard.press("Escape");
    }
  }
  await screen(page, r, "smtp-checked", { narrow: false });
  r.save();
};

// 12d. Администратор: «Продолжить настройку» → шаг банковских реквизитов — форма.
scenarios["12d"] = async (browser) => {
  const r = new Report("12d");
  const page = await as(browser, r, "admin");
  await spaGoto(page, "/admin/setup");
  await settle(page);
  const all = await seen(page, "main", 6000);
  obs(r, "мастер", { sees: all.slice(all.indexOf("Банковские"), all.indexOf("Банковские") + 900) });
  const card = page.locator("section, .ant-card, article").filter({ hasText: "Банковские реквизиты для счетов" }).first();
  await step(page, r, "действие шага реквизитов", async () => {
    await card.getByRole("button").or(card.getByRole("link")).first().click();
    await page.waitForTimeout(2500);
    await settle(page);
  });
  obs(r, "форма реквизитов", { sees: `${page.url()}\n${await seen(page, PANEL, 2500) || await seen(page, "main", 2500)}` });
  await screen(page, r, "bank-form", { narrow: false });
  r.save();
};

// 12e. Администратор: «Компания · Реквизиты» → добавить банковский счёт (UZS, 20 цифр, МФО).
scenarios["12e"] = async (browser) => {
  const r = new Report("12e");
  const page = await as(browser, r, "admin");
  await spaGoto(page, "/admin/company?section=bank");
  await settle(page);
  const all = await seen(page, "main", 8000);
  const i = all.search(/Банковск|Расчётн|Счета компании/);
  obs(r, "раздел счетов", { sees: all.slice(Math.max(0, i), i + 800) });
  await step(page, r, "«Добавить счёт»", async () => {
    await page.getByRole("button", { name: /Добавить (счёт|банковский счёт|реквизиты)/ }).first().click();
    await page.waitForTimeout(2000);
  });
  const panel = page.locator(PANEL);
  const labels = await panel.locator("label").allInnerTexts();
  obs(r, "форма счёта", { sees: labels.join(" | ") });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/12e-bank-form-1440.png` });
  r.save();
};

// 12f. Администратор: основной счёт в сумах — МФО, 20 цифр, банк; «Сохранить».
scenarios["12f"] = async (browser) => {
  const r = new Report("12f");
  const page = await as(browser, r, "admin");
  await spaGoto(page, "/admin/company?section=bank");
  await settle(page);
  await page.getByRole("button", { name: "Добавить счёт" }).first().click();
  await page.waitForTimeout(2000);
  const panel = page.locator(PANEL);
  await step(page, r, "счёт заполнен", async () => {
    await panel.getByLabel("МФО").fill("00014");
    await page.waitForTimeout(1500);
    await panel.getByLabel("Расчётный счёт").fill("20208000900123456001");
    const bank = panel.getByLabel("Банк");
    if (await bank.isEditable().catch(() => false) && !(await bank.inputValue().catch(() => ""))) await bank.fill("Демо Банк");
    const main = panel.getByLabel("Основной для этой валюты");
    if (await main.count() && !(await main.isChecked().catch(() => true))) await main.check();
  });
  obs(r, "форма перед сохранением", { sees: await seen(page, PANEL, 1500) });
  await step(page, r, "«Сохранить»", async () => {
    await panel.getByRole("button", { name: /^(Сохранить|Добавить)/ }).last().click();
    await page.waitForTimeout(4000);
    await settle(page);
  });
  const all = await seen(page, "main", 6000);
  const i = all.indexOf("Банковские счета");
  obs(r, "после сохранения", { sees: `${all.slice(0, 160)}\n…\n${all.slice(i, i + 500)}\nпанель: ${await seen(page, PANEL, 600)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/12f-bank-saved-1440.png` });
  r.save();
};

// 12g. Администратор: «Полномочия подписи» — что есть на свежей установке и как выдать директору.
scenarios["12g"] = async (browser) => {
  const r = new Report("12g");
  const page = await as(browser, r, "admin");
  await spaGoto(page, "/admin/signing");
  await settle(page);
  obs(r, "Полномочия подписи", { sees: `${page.url()}\n${await seen(page, "main", 2500)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/12g-signing-1440.png` });
  r.save();
};

// 12h. Администратор: «Выдать полномочие» директору — по уставу, все виды документов.
scenarios["12h"] = async (browser) => {
  const r = new Report("12h");
  const page = await as(browser, r, "admin");
  await spaGoto(page, "/admin/signing");
  await settle(page);
  await page.getByRole("button", { name: "Выдать полномочие" }).first().click();
  await page.waitForTimeout(2000);
  const drawer = page.locator(".ant-drawer-content").last();
  const pickIn = async (label, text, all = false) => {
    await drawer.locator(".ant-form-item").filter({ hasText: label }).locator(".ant-select").first().click();
    await page.waitForTimeout(800);
    const opts = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option");
    if (all) {
      const n = await opts.count();
      obs(r, "виды документов в списке", { sees: (await opts.allInnerTexts()).join(" | ") });
      for (let k = 0; k < n; k++) await opts.nth(k).click();
    } else await opts.filter({ hasText: text }).first().click();
    await drawer.getByText("Выдать полномочие подписи").first().click();
    await page.waitForTimeout(400);
  };
  await step(page, r, "полномочие директору по уставу", async () => {
    await pickIn("Сотрудник", "Директорова");
    await pickIn("Что подписывает", null, true);
    await drawer.getByText("Устав", { exact: true }).click();
    await page.waitForTimeout(800);
    obs(r, "форма при «Устав»", { sees: await seen(page, ".ant-drawer-content", 1200) });
    await drawer.getByRole("button", { name: "Сохранить" }).click();
    await page.waitForTimeout(4000);
    await settle(page);
  });
  const err = await seen(page, ".ant-message, .ant-notification, .ant-form-item-explain-error", 600);
  if (err) obs(r, "сообщение", { sees: err });
  obs(r, "после выдачи", { sees: (await seen(page, "main", 1500)) });
  r.save();
};

// 12i. Администратор: «Продолжить настройку» → шаг «Telegram-бот» и что осталось; «Подключения» сейчас.
scenarios["12i"] = async (browser) => {
  const r = new Report("12i");
  const page = await as(browser, r, "admin");
  await settle(page);
  obs(r, "баннер настройки", { sees: (await seen(page, "main", 400)) });
  await step(page, r, "«Продолжить настройку»", async () => {
    await page.getByRole("button", { name: "Продолжить настройку" }).or(page.getByRole("link", { name: "Продолжить настройку" })).first().click();
    await page.waitForTimeout(2500);
    await settle(page);
  });
  obs(r, "мастер настройки", { sees: `${page.url()}\n${await seen(page, "main", 3000)}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/12i-setup-1440.png` });
  await spaGoto(page, "/admin/integrations");
  await settle(page);
  obs(r, "«Подключения»", { sees: `${page.url()}\n${await seen(page, "main", 2500)}` });
  r.save();
};

// 12j. Администратор: «Подключения · Telegram» — что нужно для бота.
scenarios["12j"] = async (browser) => {
  const r = new Report("12j");
  const page = await as(browser, r, "admin");
  await spaGoto(page, "/admin/integrations");
  await settle(page);
  await page.getByRole("tab", { name: "Telegram" }).click().catch(async () => page.getByText("Telegram", { exact: true }).first().click());
  await page.waitForTimeout(2000);
  await settle(page);
  obs(r, "«Подключения · Telegram»", { sees: `${page.url()}\n${(await seen(page, "main", 3000)).replace(/^[\s\S]*?Скрыть до завтра/, "")}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/12j-telegram-1440.png` });
  r.save();
};
