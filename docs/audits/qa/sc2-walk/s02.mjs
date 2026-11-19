// Сценарий 2. Решение клиента по КП → договор → подпись (клиент — в Кабинете, письма — в Mailpit стенда).
import { execSync } from "node:child_process";
import { PANEL, Report, as, obs, screen, seen, settle, spaGoto, step } from "./common.mjs";
export const scenarios = {};

/** Письма Mailpit стенда: [{ID, Subject, To, Created}] — новые первыми. */
export function mailbox() {
  const raw = execSync("docker exec rt-scen-mailpit wget -qO- http://localhost:8025/api/v1/messages", { encoding: "utf8" });
  return JSON.parse(raw).messages ?? [];
}
export function mailText(id) {
  const raw = execSync(`docker exec rt-scen-mailpit wget -qO- http://localhost:8025/api/v1/message/${id}`, { encoding: "utf8" });
  const m = JSON.parse(raw);
  return { subject: m.Subject, text: m.Text ?? "", html: m.HTML ?? "", attachments: (m.Attachments ?? []).map((a) => a.FileName) };
}

// 2a. Менеджер: карточка клиента → «Отправить ещё раз» приглашение в кабинет (почта теперь настроена).
scenarios["2a"] = async (browser) => {
  const r = new Report("2a");
  const page = await as(browser, r, "manager_all");
  await spaGoto(page, "/crm/clients?client=1&panel=open&tab=card");
  await settle(page);
  const before = mailbox().length;
  obs(r, "приглашение в карточке клиента", { sees: (await seen(page, PANEL, 4000)).split("Приглашение в кабинет")[1]?.slice(0, 300) ?? "" });
  await step(page, r, "«Отправить ещё раз»", async () => {
    await page.locator(PANEL).getByRole("button", { name: "Отправить ещё раз" }).first().click();
    await page.waitForTimeout(6000);
    await settle(page);
  });
  obs(r, "после «Отправить ещё раз»", { sees: (await seen(page, PANEL, 4000)).split("Приглашение в кабинет")[1]?.slice(0, 300) ?? "" });
  const fresh = mailbox().slice(0, Math.max(0, mailbox().length - before));
  for (const m of fresh) {
    const t = mailText(m.ID);
    obs(r, `письмо «${t.subject}»`, { sees: `кому: ${m.To.map((x) => x.Address).join(", ")}\nвложения: ${t.attachments.join(", ") || "—"}\n${t.text.slice(0, 900)}` });
  }
  await screen(page, r, "invitation-resent", { narrow: false });
  r.save();
};

const CAB = process.env.QA_CABINET ?? "http://cabinet.localhost:8111";
import { np } from "./common.mjs";

// 2b. Клиент: ссылка из приглашения → Кабинет → КП → «Принять» → код из письма → результат.
scenarios["2b"] = async (browser) => {
  const r = new Report("2b");
  const { page } = await np(browser, 1440);
  const invite = mailbox().find((m) => /Приглашение в личный кабинет/.test(m.Subject));
  const link = /(http:\/\/cabinet\.localhost:8111\/auth\/magic#token=\S+)/.exec(invite ? mailText(invite.ID).text : "")?.[1];
  r.check("ссылка из приглашения найдена", !!link);
  await page.goto(link);
  await page.waitForTimeout(4000);
  await settle(page);
  obs(r, "Кабинет после входа по ссылке", { sees: `${page.url()}\n${await seen(page, "body", 1800)}` });
  await screen(page, r, "cabinet-home", { narrow: true });
  await page.goto(`${CAB}/quotes`);
  await page.waitForTimeout(2500);
  await settle(page);
  obs(r, "КП в Кабинете", { sees: await seen(page, "main", 1200) });
  await step(page, r, "КП открывается", async () => {
    await page.getByText("QT-2026/001").first().click();
    await page.waitForTimeout(2500);
    await settle(page);
  });
  obs(r, "карточка КП у клиента", { sees: `${page.url()}\n${await seen(page, "main", 2500)}` });
  await screen(page, r, "cabinet-quote", { narrow: true });
  const before = mailbox().length;
  await step(page, r, "«Принять» → «Получить код»", async () => {
    await page.getByRole("button", { name: "Принять" }).first().click();
    await page.waitForTimeout(1200);
    obs(r, "окно принятия", { sees: await seen(page, '[role="dialog"]', 900) });
    await page.getByRole("dialog").getByRole("button", { name: /Получить код|Отправить код/ }).first().click();
    await page.waitForTimeout(5000);
  });
  obs(r, "окно после «Получить код»", { sees: await seen(page, '[role="dialog"]', 900) });
  const fresh = mailbox().slice(0, Math.max(0, mailbox().length - before));
  const codeMail = fresh.find((m) => /код/i.test(m.Subject));
  const t = codeMail ? mailText(codeMail.ID) : null;
  if (t) obs(r, `письмо «${t.subject}»`, { sees: t.text.slice(0, 600) });
  const code = /\b(\d{6})\b/.exec(t?.text ?? "")?.[1];
  r.check("код пришёл письмом", !!code);
  await step(page, r, "код введён, КП принято", async () => {
    await page.getByRole("dialog").getByRole("textbox").first().fill(code ?? "");
    await page.getByRole("dialog").getByRole("button", { name: /Подтвердить|Принять/ }).last().click();
    await page.waitForTimeout(5000);
    await settle(page);
  });
  obs(r, "после принятия", { sees: `${page.url()}\n${await seen(page, "main", 2500)}` });
  await screen(page, r, "cabinet-quote-accepted", { narrow: true });
  const after = mailbox().slice(0, Math.max(0, mailbox().length - before));
  for (const m of after) obs(r, `письмо после принятия: «${m.Subject}»`, { sees: `кому: ${m.To.map((x) => x.Address).join(", ")}` });
  await page.context().storageState({ path: `${process.env.QA_OUT}/cab-state.json` });
  r.save();
};

// 2c. Клиент: «К договорам» → договор → что предлагает (согласовать, скачать, подписать); имя скачанного PDF.
scenarios["2c"] = async (browser) => {
  const r = new Report("2c");
  const { page } = await np(browser, 1440, { storageState: `${process.env.QA_OUT}/cab-state.json` });
  await page.goto(`${CAB}/contracts`);
  await page.waitForTimeout(2500);
  await settle(page);
  obs(r, "Договоры", { sees: await seen(page, "main", 1200) });
  await step(page, r, "договор открывается", async () => {
    await page.getByText(/CT-2026\/001/).first().click();
    await page.waitForTimeout(2500);
    await settle(page);
  });
  obs(r, "карточка договора у клиента", { sees: `${page.url()}\n${await seen(page, "main", 2500)}` });
  await screen(page, r, "cabinet-contract", { narrow: true });
  const dl = page.getByRole("button", { name: /Скачать/ }).or(page.getByRole("link", { name: /Скачать/ })).first();
  if (await dl.isVisible().catch(() => false)) {
    const [download] = await Promise.all([page.waitForEvent("download", { timeout: 20000 }).catch(() => null), dl.click()]);
    obs(r, "имя скачанного файла договора", { sees: download ? download.suggestedFilename() : "скачивание не началось" });
  }
  r.save();
};

// 2d. Клиент: КП → «Скачать» — имя файла (ДОК-12).
scenarios["2d"] = async (browser) => {
  const r = new Report("2d");
  const { page } = await np(browser, 1440, { storageState: `${process.env.QA_OUT}/cab-state.json` });
  await page.goto(`${CAB}/quotes/1`);
  await page.waitForTimeout(2500);
  await settle(page);
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: 20000 }).catch(() => null),
    page.getByRole("button", { name: "Скачать" }).or(page.getByRole("link", { name: "Скачать" })).first().click(),
  ]);
  obs(r, "имя скачанного файла КП", { sees: download ? download.suggestedFilename() : "скачивание не началось" });
  r.save();
};

// 2e. Клиент: «Согласовать» договор — что видит и что дальше.
scenarios["2e"] = async (browser) => {
  const r = new Report("2e");
  const { page } = await np(browser, 1440, { storageState: `${process.env.QA_OUT}/cab-state.json` });
  await page.goto(`${CAB}/contracts`);
  await page.waitForTimeout(2500);
  await settle(page);
  const before = mailbox().length;
  await step(page, r, "«Согласовать»", async () => {
    await page.getByRole("button", { name: "Согласовать" }).first().click();
    await page.waitForTimeout(1500);
    const dlg = await seen(page, '[role="dialog"]', 900);
    if (dlg) {
      obs(r, "окно согласования", { sees: dlg });
      await page.getByRole("dialog").getByRole("button", { name: /Согласовать|Подтвердить|Получить код/ }).last().click();
      await page.waitForTimeout(5000);
      const dlg2 = await seen(page, '[role="dialog"]', 900);
      if (dlg2) obs(r, "окно после первого шага", { sees: dlg2 });
      const fresh = mailbox().slice(0, Math.max(0, mailbox().length - before));
      const code = /\b(\d{6})\b/.exec(fresh.map((m) => mailText(m.ID).text).join("\n"))?.[1];
      if (code && (await page.getByRole("dialog").getByRole("textbox").count())) {
        await page.getByRole("dialog").getByRole("textbox").first().fill(code);
        await page.getByRole("dialog").getByRole("button", { name: /Согласовать|Подтвердить/ }).last().click();
        await page.waitForTimeout(5000);
      }
    }
    await settle(page);
  });
  obs(r, "после согласования", { sees: `${page.url()}\n${await seen(page, "main", 1500)}` });
  for (const m of mailbox().slice(0, Math.max(0, mailbox().length - before))) obs(r, `письмо: «${m.Subject}»`, { sees: `кому: ${m.To.map((x) => x.Address).join(", ")}` });
  await screen(page, r, "cabinet-contract-agreed", { narrow: true });
  r.save();
};

// 2f. Сотрудники после согласования клиентом: «Задачи» менеджера и директора, колокольчик.
scenarios["2f"] = async (browser) => {
  const r = new Report("2f");
  for (const role of ["manager_all", "director"]) {
    const page = await as(browser, r, role);
    await spaGoto(page, "/dashboard/queue");
    await settle(page);
    const q = await seen(page, "main", 2000);
    obs(r, `«Задачи» (${role})`, { sees: q.slice(q.indexOf("Что сделать сейчас")) });
    await page.getByRole("button", { name: /уведомлен/i }).first().click().catch(() => {});
    await page.waitForTimeout(1500);
    obs(r, `колокольчик (${role})`, { sees: await seen(page, ".ant-drawer, .ant-popover, [role=dialog]", 1200) });
    await screen(page, r, `queue-after-agree-${role}`, { narrow: false });
    await page.close();
  }
  r.save();
};

// 2g. Менеджер: строка «Выставить у оператора договор» → что предлагает экран без подключённого ЭДО.
scenarios["2g"] = async (browser) => {
  const r = new Report("2g");
  const page = await as(browser, r, "manager_all");
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  await step(page, r, "строка задачи открывает договор", async () => {
    await page.getByRole("link", { name: /Открыть/ }).first().click();
    await page.waitForTimeout(3000);
    await settle(page);
  });
  obs(r, "экран договора", { sees: `${page.url()}\n${await seen(page, "main", 2500)}` });
  obs(r, "панель", { sees: await seen(page, PANEL, 2500) });
  await screen(page, r, "contract-staff", { narrow: false });
  r.save();
};

// 2h. Менеджер: «Отметить: выставлен у оператора» → что дальше; затем скан подписанного договора.
scenarios["2h"] = async (browser) => {
  const r = new Report("2h");
  const page = await as(browser, r, "manager_all");
  await spaGoto(page, "/eds/projects/PRJ-2026-001?panel=open&tab=contract");
  await settle(page);
  const panel = page.locator(PANEL);
  await step(page, r, "«Отметить: выставлен у оператора»", async () => {
    await panel.getByLabel(/Оператор или номер/).fill("Didox, № 0001");
    await panel.getByRole("button", { name: /Отметить: выставлен у оператора/ }).click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) {
      obs(r, "подтверждение", { sees: await seen(page, '[role="dialog"]', 500) });
      await dlg.getByRole("button").last().click();
    }
    await page.waitForTimeout(4000);
    await settle(page);
  });
  obs(r, "панель после «выставлен»", { sees: await seen(page, PANEL, 2000) });
  await screen(page, r, "contract-issued", { narrow: false });
  const file = panel.locator('input[type="file"]').first();
  if (await file.count()) {
    await step(page, r, "скан подписанного договора", async () => {
      await file.setInputFiles(process.env.SC2_LETTER);
      await page.waitForTimeout(2000);
      const save = panel.getByRole("button", { name: /Загрузить|Сохранить|Подписан|Отметить/ });
      obs(r, "кнопки после выбора скана", { sees: (await save.allInnerTexts()).join(" | ") });
      const dlg = page.getByRole("dialog");
      if (await dlg.isVisible().catch(() => false)) { obs(r, "окно скана", { sees: await seen(page, '[role="dialog"]', 600) }); await dlg.getByRole("button").last().click(); }
      await page.waitForTimeout(5000);
      await settle(page);
    });
    obs(r, "после скана", { sees: await seen(page, PANEL, 2000) });
    obs(r, "проект после скана", { sees: (await seen(page, "main", 3000)).split("Документы проекта")[1]?.slice(0, 1200) ?? "" });
    await screen(page, r, "contract-signed", { narrow: false });
  } else {
    obs(r, "поле скана", { sees: "нет поля загрузки скана в панели", dead: "?" });
  }
  r.save();
};

// 2i. Менеджер: «Прикрепить скан» подписанного договора → «Подписан» → черновик счёта.
scenarios["2i"] = async (browser) => {
  const r = new Report("2i");
  const page = await as(browser, r, "manager_all");
  await spaGoto(page, "/eds/projects/PRJ-2026-001?panel=open&tab=contract");
  await settle(page);
  const panel = page.locator(PANEL);
  await step(page, r, "«Прикрепить скан»", async () => {
    await panel.locator('input[type="file"]').first().setInputFiles(process.env.SC2_LETTER);
    await page.waitForTimeout(1500);
    await panel.getByRole("button", { name: "Прикрепить скан" }).click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) { obs(r, "окно скана", { sees: await seen(page, '[role="dialog"]', 600) }); await dlg.getByRole("button").last().click(); }
    await page.waitForTimeout(6000);
    await settle(page);
  });
  obs(r, "панель после скана", { sees: (await seen(page, PANEL, 1500)) });
  const main = await seen(page, "main", 4000);
  obs(r, "документы проекта после скана", { sees: main.split("Документы проекта")[1]?.slice(0, 900) ?? main.slice(0, 900) });
  await screen(page, r, "contract-signed", { narrow: false });
  await spaGoto(page, "/dashboard/queue");
  await settle(page);
  const q = await seen(page, "main", 2000);
  obs(r, "«Задачи» менеджера после подписания", { sees: q.slice(q.indexOf("Что сделать сейчас")) });
  r.save();
};
