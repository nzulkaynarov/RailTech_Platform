import { PEOPLE, PANEL, Report, np, saveState, screen, settle, shot, state, step, compose } from "./common.mjs";
export const scenarios = {};
export const CAB = process.env.QA_CABINET ?? "http://cabinet.localhost:8101";
export const CLIENT_EMAIL = process.env.CLIENT_EMAIL ?? "aziz.client.d26@demo.example";
const txt = async (page, sel = "body") => (await page.locator(sel).first().innerText().catch(() => "")).replace(/\n{2,}/g, "\n");
const out = (label, t, n = 1200) => console.log(`--- ${label}\n${String(t).slice(0, n)}`);

/** SMTP на стенде нет: письмо со ссылкой не хранит тела (FAILED smtp_not_configured). Ссылку выпускаем в shell ERP той же
 *  функцией, что и задача «Выслать ссылку» (стендовая подмена канала доставки, письмо клиенту не уходит). */
export function magicUrl() {
  const o = compose(`exec -T erp-backend python manage.py shell -c "
from parties.models import Contact
from portal.models import MagicLinkToken
from portal.services.tokens import generate_token, hash_token
from portal.services.magic_link import build_login_url, LOGIN_LINK_TTL
from django.utils import timezone
c=Contact.objects.filter(email__iexact='${CLIENT_EMAIL}').first()
t=generate_token()
MagicLinkToken.objects.create(token_hash=hash_token(t), contact=c, purpose=MagicLinkToken.PURPOSE_LOGIN, expires_at=timezone.now()+LOGIN_LINK_TTL)
print('MAGIC=' + build_login_url(t))
"`);
  return /MAGIC=(\S+)/.exec(o)?.[1];
}

/** Вход клиента в кабинет по ссылке на почту (письмо читается из журнала ERP) */
export async function cabLogin(page, r, email = CLIENT_EMAIL) {
  await page.goto("/");
  await settle(page);
  const url = await (async () => {
    await page.getByLabel(/почт|e-?mail/i).first().fill(email);
    await page.getByRole("button", { name: /ссылк|войти|получить/i }).first().click();
    await page.waitForTimeout(4000);
    return magicUrl();
  })();
  if (!url || url === "NONE") throw new Error("ссылка входа не найдена в журнале писем ERP");
  await page.goto(url);
  await page.waitForTimeout(3000);
  await settle(page);
}

import { existsSync } from "node:fs";
import { resolve } from "node:path";
const CAB_STATE = () => resolve(process.env.QA_OUT ?? "/tmp", process.env.CLIENT_EMAIL ? `cab-state-${process.env.CLIENT_EMAIL.split("@")[0]}.json` : "cab-state.json");

/** Страница клиента: сессия кабинета сохраняется вне репозитория (лимит ссылок входа — 5 в час на адрес) */
export async function cabPage(browser, r, width = 1440) {
  const opts = { baseURL: CAB };
  if (existsSync(CAB_STATE())) opts.storageState = CAB_STATE();
  const { ctx, page } = await np(browser, width, opts);
  if (!existsSync(CAB_STATE())) {
    await cabLogin(page, r);
    await ctx.storageState({ path: CAB_STATE() });
  }
  return { ctx, page };
}

scenarios.cab0 = async (browser) => {
  const r = new Report("cab0");
  const { page } = await np(browser, 1440, { baseURL: CAB });
  await page.goto("/");
  await settle(page);
  out("логин кабинета", await txt(page), 800);
  await screen(page, r, "cabinet-login", { narrow: true });
  r.save();
};

// cab1. Клиент входит по ссылке, видит главную и КП
scenarios.cab1 = async (browser) => {
  const r = new Report("cab1");
  const { page } = await cabPage(browser, r);
  await page.goto("/");
  await settle(page);
  out("главная кабинета", await txt(page), 1500);
  await screen(page, r, "cabinet-home", { narrow: true });
  await page.goto("/quotes");
  await settle(page);
  out("КП", await txt(page), 1500);
  await screen(page, r, "cabinet-quotes", { narrow: true });
  r.save();
};

// cab2. Клиент открывает КП: состав, «Принять» (код в Telegram) с комментарием
scenarios.cab2 = async (browser) => {
  const r = new Report("cab2");
  const { page } = await cabPage(browser, r);
  await page.goto("/quotes");
  await settle(page);
  await page.getByRole("link", { name: new RegExp(process.env.QUOTE ?? "КП-2026-00001") }).first().click();
  await settle(page);
  out(`КП ${page.url()}`, await txt(page), 2500);
  await screen(page, r, "cabinet-quote-page", { narrow: true });
  r.save();
};

// cab3. Клиент пишет комментарий к КП (B-CABFIX-1), затем «Принять»: код приходит в Telegram клиента (заглушка Bot API)
scenarios.cab3 = async (browser) => {
  const r = new Report("cab3");
  const { page } = await cabPage(browser, r);
  await page.goto("/quotes");
  await settle(page);
  await page.getByRole("link", { name: new RegExp(process.env.QUOTE ?? "КП-2026-00001") }).first().click();
  await settle(page);
  await step(page, r, "клиент отправляет комментарий к КП", async () => {
    await page.getByLabel("Ваш комментарий").fill("Просим уточнить срок поставки рельсов: нужно до 20 ноября, и можно ли отгрузить частями.");
    await page.getByRole("button", { name: "Отправить комментарий" }).click();
    await page.getByText(/Просим уточнить срок поставки/).first().waitFor({ timeout: 15000 });
  });
  await settle(page);
  await screen(page, r, "cabinet-quote-comment-sent", { narrow: true });
  await step(page, r, "клиент нажимает «Принять»", async () => {
    await page.getByRole("button", { name: "Принять" }).first().click();
    await page.waitForTimeout(2500);
  });
  out("после «Принять»", await txt(page, "[role=dialog], main"), 1500);
  await screen(page, r, "cabinet-quote-accept-dialog", { narrow: false });
  r.save();
};

/** Последние сообщения заглушки Bot API клиенту (chat_id) */
export async function botTexts(chatId, n = 5) {
  const d = await (await fetch("http://127.0.0.1:18999/_log")).json();
  const list = Array.isArray(d) ? d : d.log ?? [];
  return list.filter((x) => x.method === "sendMessage" && String(x.chat_id) === String(chatId)).slice(-n).map((x) => x.text ?? "");
}

// cab4. Клиент принимает КП: «Получить код» -> код из Telegram (заглушка) -> подтверждение -> проект
scenarios.cab4 = async (browser) => {
  const r = new Report("cab4");
  const { page } = await cabPage(browser, r);
  await page.goto("/quotes");
  await settle(page);
  await page.getByRole("link", { name: new RegExp(process.env.QUOTE ?? "КП-2026-00001") }).first().click();
  await settle(page);
  await page.getByRole("button", { name: "Принять" }).first().click();
  const dlg = page.getByRole("dialog");
  await dlg.getByRole("button", { name: "Получить код" }).click();
  await page.waitForTimeout(4000);
  out("диалог после «Получить код»", await txt(page, "[role=dialog]"), 800);
  await shot(page, r, "cabinet-accept-code-step");
  const texts = await botTexts(process.env.CHAT ?? 7001, 3);
  console.log("BOT:", texts.map((t) => t.replace(/\d{4,8}/g, "<код>").slice(0, 120)).join(" || "));
  const code = /\b(\d{4,8})\b/.exec(texts.at(-1) ?? "")?.[1];
  r.check("код подтверждения пришёл клиенту в Telegram", !!code);
  await step(page, r, "клиент вводит код и принимает КП", async () => {
    await dlg.getByRole("textbox").first().fill(code ?? "");
    await dlg.getByRole("button", { name: /Подтвердить|Принять/ }).last().click();
    await page.waitForTimeout(4000);
  });
  await settle(page);
  out("после принятия", await txt(page, "main"), 1800);
  await screen(page, r, "cabinet-quote-accepted", { narrow: true });
  r.save();
};

// cab5. Клиент: «Договоры» -> согласовать редакцию договора
scenarios.cab5 = async (browser) => {
  const r = new Report("cab5");
  const { page } = await cabPage(browser, r);
  await page.goto("/contracts");
  await settle(page);
  out(`договоры ${page.url()}`, await txt(page, "main"), 800);
  await screen(page, r, "cabinet-contracts", { narrow: true });
  await page.getByRole("link", { name: /CT-2026-00001|СТ-2026-00001/ }).first().click();
  await settle(page);
  out(`договор ${page.url()}`, await txt(page, "main"), 1800);
  await screen(page, r, "cabinet-contract-page", { narrow: true });
  r.save();
};

async function download(page, trigger, name) {
  const dir = resolve(process.env.QA_OUT ?? "/tmp", "files");
  const { mkdirSync } = await import("node:fs");
  mkdirSync(dir, { recursive: true });
  const [dl] = await Promise.all([page.waitForEvent("download", { timeout: 30000 }), trigger()]);
  const path = resolve(dir, name);
  await dl.saveAs(path);
  return path;
}

// cab6. Клиент скачивает PDF договора и согласует редакцию
scenarios.cab6 = async (browser) => {
  const r = new Report("cab6");
  const { page } = await cabPage(browser, r);
  await page.goto("/contracts");
  await settle(page);
  await step(page, r, "клиент скачивает PDF договора", async () => {
    const p = await download(page, () => page.getByRole("button", { name: /Скачать/ }).or(page.getByRole("link", { name: /Скачать/ })).first().click(), "contract-draft.pdf");
    console.log("PDF сохранён:", p);
  });
  await step(page, r, "клиент согласует редакцию договора", async () => {
    await page.getByRole("button", { name: "Согласовать" }).first().click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.count()) {
      out("диалог", await txt(page, "[role=dialog]"), 600);
      await shot(page, r, "cabinet-contract-agree-dialog");
      await dlg.getByRole("button", { name: /Согласовать|Подтвердить/ }).last().click();
    }
    await page.waitForTimeout(3000);
  });
  await settle(page);
  out("договоры после", await txt(page, "main"), 800);
  await screen(page, r, "cabinet-contract-agreed", { narrow: true });
  r.save();
};

// cab7. Клиент: «Счета» -> счёт -> «Я оплатил» с файлом платёжки
scenarios.cab7 = async (browser) => {
  const r = new Report("cab7");
  const { page } = await cabPage(browser, r);
  await page.goto("/invoices");
  await settle(page);
  out(`счета ${page.url()}`, await txt(page, "main"), 900);
  await screen(page, r, "cabinet-invoices", { narrow: true });
  await page.getByRole("link", { name: /INV-2026-00001/ }).first().click();
  await settle(page);
  out(`счёт ${page.url()}`, await txt(page, "main"), 2200);
  await screen(page, r, "cabinet-invoice-page", { narrow: true });
  r.save();
};

// cab8. Клиент: «Я оплатил» — файл платёжки (PROOF=payment-proof) и сумма (AMOUNT, необязательно)
scenarios.cab8 = async (browser) => {
  const r = new Report("cab8");
  const { page } = await cabPage(browser, r);
  await page.goto("/invoices");
  await settle(page);
  await page.getByRole("button", { name: "Я оплатил" }).first().click();
  await page.waitForTimeout(1200);
  const dlg = page.getByRole("dialog");
  out("диалог «Я оплатил»", await txt(page, "[role=dialog]"), 1200);
  await shot(page, r, "cabinet-paid-dialog");
  await step(page, r, "клиент прикладывает платёжку и подтверждает", async () => {
    await dlg.locator('input[type="file"]').first().setInputFiles(`${process.env.QA_OUT}/demo/${process.env.PROOF ?? "payment-proof"}.pdf`);
    if (process.env.AMOUNT) await dlg.getByLabel(/Сумма/).fill(process.env.AMOUNT).catch((e) => console.log("сумма:", String(e.message).split("\n")[0]));
    await shot(page, r, "cabinet-paid-filled");
    await dlg.getByRole("button", { name: /Отправить|Подтвердить|Я оплатил/ }).last().click();
    await page.waitForTimeout(3500);
  });
  await settle(page);
  out("после", await txt(page, "main"), 900);
  await screen(page, r, "cabinet-paid-sent", { narrow: true });
  r.save();
};

// cab9. Клиент: «Акты» -> «Вернуть» с причиной (ACT_MODE=return) или «Принять» (ACT_MODE=accept)
scenarios.cab9 = async (browser) => {
  const r = new Report("cab9");
  const mode = process.env.ACT_MODE ?? "return";
  const { page } = await cabPage(browser, r);
  await page.goto("/acts");
  await settle(page);
  out(`акты ${page.url()}`, await txt(page, "main"), 900);
  await screen(page, r, `cabinet-acts-${mode}-before`, { narrow: true });
  const dlPdf = await page.getByRole("button", { name: /Скачать/ }).or(page.getByRole("link", { name: /Скачать/ })).count();
  console.log("кнопок «Скачать»:", dlPdf);
  if (dlPdf) await step(page, r, "клиент скачивает PDF акта", async () => {
    const p = await download(page, () => page.getByRole("button", { name: /Скачать/ }).or(page.getByRole("link", { name: /Скачать/ })).first().click(), "act.pdf");
    console.log("PDF:", p);
  });
  if (mode === "return") {
    await page.getByRole("button", { name: /Вернуть/ }).first().click();
    await page.waitForTimeout(1000);
    out("диалог «Вернуть»", await txt(page, "[role=dialog]"), 900);
    await shot(page, r, "cabinet-act-return-dialog");
    await step(page, r, "клиент возвращает акт с причиной", async () => {
      const dlg = page.getByRole("dialog");
      await dlg.getByRole("textbox").first().fill("В акте не указана доставка отдельной строкой; просим выпустить акт заново.");
      await dlg.getByRole("button", { name: /Вернуть/ }).last().click();
      await page.waitForTimeout(3500);
    });
  } else {
    await page.getByRole("button", { name: /Принять/ }).first().click();
    await page.waitForTimeout(1000);
    out("диалог «Принять»", await txt(page, "[role=dialog]"), 900);
    await shot(page, r, "cabinet-act-accept-dialog");
    await step(page, r, "клиент принимает акт", async () => {
      const dlg = page.getByRole("dialog");
      await dlg.getByRole("button", { name: /Принять/ }).last().click();
      await page.waitForTimeout(3500);
    });
  }
  await settle(page);
  out("после", await txt(page, "main"), 900);
  await screen(page, r, `cabinet-acts-${mode}-after`, { narrow: true });
  r.save();
};

// cab11. Клиент скачивает PDF КП (без себестоимости и маржи)
scenarios.cab11 = async (browser) => {
  const r = new Report("cab11");
  const { page } = await cabPage(browser, r);
  await page.goto("/quotes");
  await settle(page);
  await page.getByRole("link", { name: new RegExp(process.env.QUOTE ?? "КП-2026-00001") }).first().click();
  await settle(page);
  await step(page, r, "клиент скачивает PDF КП", async () => {
    const p = await download(page, () => page.getByRole("button", { name: /Скачать/ }).or(page.getByRole("link", { name: /Скачать/ })).first().click(), "quote.pdf");
    console.log("PDF:", p);
  });
  r.save();
};
