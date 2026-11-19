// Сценарий 3. Счёт → платёжка → подтверждение оплаты.
import { PANEL, Report, as, obs, screen, seen, settle, spaGoto, step } from "./common.mjs";
export const scenarios = {};

// 3a. Менеджер: строка «Выставить счёт» → счёт; банковских реквизитов у компании нет (ветка «не настроено»).
scenarios["3a"] = async (browser) => {
  const r = new Report("3a");
  const page = await as(browser, r, "manager_all");
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  await step(page, r, "строка «Выставить счёт» открывает счёт", async () => {
    await page.getByRole("link", { name: /Открыть/ }).first().click();
    await page.waitForTimeout(3000);
    await settle(page);
  });
  obs(r, "экран счёта", { sees: `${page.url()}\n${await seen(page, "main", 1500)}` });
  obs(r, "панель счёта", { sees: await seen(page, PANEL, 2500) });
  await screen(page, r, "invoice-draft", { narrow: false });
  const issue = page.locator(PANEL).getByRole("button", { name: /Выставить счёт/ }).first();
  if (await issue.isVisible().catch(() => false)) {
    obs(r, "кнопка «Выставить счёт»", { sees: `активна: ${await issue.isEnabled()}` });
    if (await issue.isEnabled()) {
      await step(page, r, "«Выставить счёт»", async () => {
        await issue.click();
        await page.waitForTimeout(1500);
        const dlg = page.getByRole("dialog");
        if (await dlg.isVisible().catch(() => false)) { obs(r, "окно", { sees: await seen(page, '[role="dialog"]', 600) }); await dlg.getByRole("button").last().click(); }
        await page.waitForTimeout(5000);
        await settle(page);
      });
      obs(r, "после «Выставить счёт»", { sees: await seen(page, PANEL, 2000) });
      const err = await seen(page, ".ant-message, .ant-notification, [role=alert]", 600);
      if (err) obs(r, "сообщение", { sees: err });
      await screen(page, r, "invoice-issue-result", { narrow: false });
    }
  }
  r.save();
};

import { mailbox, mailText } from "./s02.mjs";

// 3b. Менеджер: «Выставить счёт» (реквизиты есть) → что получает клиент; имя PDF счёта в Платформе.
scenarios["3b"] = async (browser) => {
  const r = new Report("3b");
  const page = await as(browser, r, "manager_all");
  await spaGoto(page, "/eds/payments/1?panel=open&tab=payment");
  await settle(page);
  const before = mailbox().length;
  await step(page, r, "«Выставить счёт»", async () => {
    await page.locator(PANEL).getByRole("button", { name: /Выставить счёт/ }).first().click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) { obs(r, "окно", { sees: await seen(page, '[role="dialog"]', 600) }); await dlg.getByRole("button").last().click(); }
    await page.waitForTimeout(8000);
    await settle(page);
  });
  obs(r, "панель после «Выставить счёт»", { sees: await seen(page, PANEL, 1500) });
  for (const m of mailbox().slice(0, Math.max(0, mailbox().length - before))) {
    const t = mailText(m.ID);
    obs(r, `письмо «${t.subject}»`, { sees: `кому: ${m.To.map((x) => x.Address).join(", ")}; вложения: ${t.attachments.join(", ") || "—"}\n${t.text.slice(0, 500)}` });
  }
  const dl = page.getByRole("link", { name: /PDF|Скачать/ }).or(page.getByRole("button", { name: /PDF|Скачать/ })).first();
  if (await dl.isVisible().catch(() => false)) {
    const [download] = await Promise.all([page.waitForEvent("download", { timeout: 20000 }).catch(() => null), dl.click()]);
    obs(r, "имя PDF счёта в Платформе", { sees: download ? download.suggestedFilename() : "скачивание не началось" });
  }
  await page.screenshot({ path: `${process.env.QA_SHOTS}/3b-invoice-issued-1440.png` });
  r.save();
};

const CAB = process.env.QA_CABINET ?? "http://cabinet.localhost:8111";
import { np } from "./common.mjs";

// 3c. Клиент: ссылка из письма «Выставлен счёт» → счёт → «Я оплатил» с файлом платёжки.
scenarios["3c"] = async (browser) => {
  const r = new Report("3c");
  const { page } = await np(browser, 1440, { storageState: `${process.env.QA_OUT}/cab-state.json` });
  await page.goto(`${CAB}/invoices?focus=1`);
  await page.waitForTimeout(3000);
  await settle(page);
  obs(r, "счёт у клиента", { sees: `${page.url()}\n${await seen(page, "main", 1800)}` });
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: 15000 }).catch(() => null),
    page.getByRole("button", { name: /Скачать/ }).or(page.getByRole("link", { name: /Скачать/ })).first().click().catch(() => {}),
  ]);
  obs(r, "имя PDF счёта в Кабинете", { sees: download ? download.suggestedFilename() : "скачивание не началось" });
  await step(page, r, "«Я оплатил»", async () => {
    await page.getByRole("button", { name: /Я оплатил/ }).first().click();
    await page.waitForTimeout(1500);
  });
  obs(r, "окно «Я оплатил»", { sees: await seen(page, '[role="dialog"]', 900) });
  await step(page, r, "платёжка приложена и отправлена", async () => {
    const dlg = page.getByRole("dialog");
    await dlg.locator('input[type="file"]').first().setInputFiles(process.env.SC2_LETTER);
    await page.waitForTimeout(1500);
    await dlg.getByRole("button", { name: /Отправить|Сообщить|Готово|Я оплатил/ }).last().click();
    await page.waitForTimeout(5000);
    await settle(page);
  });
  obs(r, "после «Я оплатил»", { sees: await seen(page, "main", 1500) });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/3c-cabinet-paid-1440.png` });
  r.save();
};

// 3d. Бухгалтер: «Задачи» → платёжка клиента → «Подтвердить оплату» → что дальше у всех.
scenarios["3d"] = async (browser) => {
  const r = new Report("3d");
  const page = await as(browser, r, "accountant");
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  const q = await seen(page, "main", 2000);
  obs(r, "«Задачи» бухгалтера", { sees: q.slice(q.indexOf("Что сделать сейчас")) });
  await step(page, r, "строка платёжки открывает счёт", async () => {
    await page.getByRole("link", { name: /Открыть/ }).first().click();
    await page.waitForTimeout(3000);
    await settle(page);
  });
  obs(r, "счёт у бухгалтера", { sees: `${page.url()}\n${await seen(page, PANEL, 1800)}` });
  const panel = page.locator(PANEL);
  const before = mailbox().length;
  await step(page, r, "«Подтвердить оплату» на всю сумму", async () => {
    await panel.getByLabel(/Сумма по выписке/).fill("1868160");
    await panel.getByLabel(/Номер операции банка/).fill("OP-0001").catch(() => {});
    await panel.getByRole("button", { name: /^Подтвердить оплату/ }).click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) { obs(r, "окно", { sees: await seen(page, '[role="dialog"]', 600) }); await dlg.getByRole("button").last().click(); }
    await page.waitForTimeout(6000);
    await settle(page);
  });
  obs(r, "после подтверждения", { sees: await seen(page, PANEL, 1500) });
  const err = await seen(page, ".ant-message, .ant-notification, [role=alert]", 600);
  if (err) obs(r, "сообщение", { sees: err });
  for (const m of mailbox().slice(0, Math.max(0, mailbox().length - before))) obs(r, `письмо «${m.Subject}»`, { sees: `кому: ${m.To.map((x) => x.Address).join(", ")}` });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/3d-payment-confirmed-1440.png` });
  r.save();
};
