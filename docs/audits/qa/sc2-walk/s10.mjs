// Сценарий 10. Каталог: позиция из заявки → карточка → проверка → публикация → клиент видит в каталоге.
import { PANEL, Report, as, np, obs, seen, settle, spaGoto, step } from "./common.mjs";
export const scenarios = {};
const CAB = process.env.QA_CABINET ?? "http://cabinet.localhost:8111";

async function buttonsOf(page, selector = "body") {
  return page.locator(`${selector} button:visible, ${selector} a[role=button]:visible, ${selector} a.ant-btn:visible`).evaluateAll((els) =>
    [...new Set(els.map((e) => `${e.innerText.trim().replace(/\s+/g, " ")}${e.disabled ? " [disabled]" : ""}`).filter(Boolean))],
  );
}

// 10a. Снабженец: расчёт RQ-2026-002 → «Начать расчёт» → строки заявки и сопоставление с каталогом.
scenarios["10a"] = async (browser) => {
  const r = new Report("10a");
  const page = await as(browser, r, "supply");
  await spaGoto(page, "/erp/calc/RQ-2026-002");
  await settle(page);
  await step(page, r, "«Начать расчёт»", async () => {
    await page.getByRole("button", { name: "Начать расчёт" }).click();
    await page.waitForTimeout(1500);
    const dlg = page.getByRole("dialog");
    if (await dlg.isVisible().catch(() => false)) { obs(r, "окно", { sees: await seen(page, '[role="dialog"]', 900) }); await dlg.getByRole("button").last().click(); }
    await page.waitForTimeout(4000);
    await settle(page);
  });
  obs(r, "расчёт после начала", { sees: `${page.url()}\n${await seen(page, "main", 3500)}` });
  obs(r, "кнопки", { sees: (await buttonsOf(page, "main")).join(" | ") });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/10a-calc-1440.png` });
  r.save();
};

// 10b. Снабженец: черновик позиции «Накладка стыковая Р65» из расчёта → карточка: поля и действия.
scenarios["10b"] = async (browser) => {
  const r = new Report("10b");
  const page = await as(browser, r, "supply");
  await spaGoto(page, "/erp/calc/RQ-2026-002");
  await settle(page);
  await step(page, r, "карточка черновика", async () => {
    await page.getByRole("link", { name: "Накладка стыковая Р65" }).or(page.getByText("Накладка стыковая Р65", { exact: true })).first().click();
    await page.waitForTimeout(3000);
    await settle(page);
  });
  const text = (await seen(page, PANEL, 4000)) || (await seen(page, "main", 4000));
  obs(r, "карточка позиции", { sees: `${page.url()}\n${text}` });
  obs(r, "кнопки", { sees: (await buttonsOf(page, "body")).join(" | ") });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/10b-item-1440.png` });
  r.save();
};

/** Подписи полей формы в области. */
async function labelsOf(page, selector) {
  return page.locator(`${selector} .ant-form-item-label label`).allInnerTexts();
}

// 10c. Снабженец: «Изменить позицию» — единица, категория, ТН ВЭД → «Сохранить» → «Опубликовать».
scenarios["10c"] = async (browser) => {
  const r = new Report("10c");
  const page = await as(browser, r, "supply");
  await spaGoto(page, "/erp/catalog?item=4&panel=open");
  await settle(page);
  const drawer = page.locator(".ant-drawer:visible").last();
  await step(page, r, "«Изменить позицию»", async () => {
    await drawer.getByRole("button", { name: "Изменить позицию" }).click();
    await page.waitForTimeout(2000);
  });
  const form = page.locator(".ant-drawer:visible, [role=dialog]:visible").last();
  obs(r, "поля формы", { sees: (await labelsOf(page, ".ant-drawer:visible")).join(" | ") });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/10c-edit-1440.png` });
  const dropdown = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option");
  const pick = async (label, typed, want) => {
    const field = form.getByLabel(label, { exact: true });
    await field.click({ force: true });
    if (typed) await page.keyboard.type(typed);
    await page.waitForTimeout(1500);
    const opts = await dropdown.allInnerTexts();
    obs(r, `варианты «${label}»`, { sees: opts.slice(0, 15).join(" | ") || "пусто" });
    if (opts.length) await (want ? dropdown.filter({ hasText: want }) : dropdown).first().click();
    await page.waitForTimeout(400);
  };
  await step(page, r, "единица", async () => pick("Единица измерения", "шт"));
  await step(page, r, "категория", async () => pick("Категория", "", "Металлопрокат"));
  await step(page, r, "МХИК — поиск «накладка»", async () => {
    const mxik = form.getByLabel(/МХИК/).first();
    await mxik.click({ force: true });
    await page.keyboard.type("накладка");
    await page.waitForTimeout(2500);
    obs(r, "подсказки МХИК", { sees: (await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option, .ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-empty").allInnerTexts()).slice(0, 8).join(" | ") || "пусто" });
    await page.keyboard.press("Escape");
  });
  await step(page, r, "код ТН ВЭД", async () => {
    await form.getByLabel(/ТН ВЭД/).first().fill("7302400000");
  });
  await step(page, r, "«Сохранить»", async () => {
    await form.getByRole("button", { name: /Сохранить/ }).last().click();
    await page.waitForTimeout(3000);
  });
  const e = (await page.locator(".ant-message:visible, .ant-form-item-explain-error:visible").allInnerTexts()).join(" | ");
  if (e) obs(r, "сообщения", { sees: e });
  const card = page.locator(".ant-drawer:visible").last();
  obs(r, "карточка после сохранения", { sees: (await card.innerText().catch(() => "")).slice(0, 1500) });
  const publish = card.getByRole("button", { name: "Опубликовать" });
  obs(r, "«Опубликовать»", { sees: `активна: ${await publish.isEnabled().catch(() => false)}` });
  if (await publish.isEnabled().catch(() => false)) {
    await step(page, r, "«Опубликовать»", async () => {
      await publish.click();
      await page.waitForTimeout(1500);
      const dlg = page.getByRole("dialog");
      if (await dlg.isVisible().catch(() => false)) { obs(r, "окно", { sees: await seen(page, '[role="dialog"]', 900) }); await dlg.getByRole("button").last().click(); }
      await page.waitForTimeout(3000);
    });
    const e2 = (await page.locator(".ant-message:visible").allInnerTexts()).join(" | ");
    if (e2) obs(r, "сообщения", { sees: e2 });
    obs(r, "после публикации", { sees: (await page.locator(".ant-drawer:visible").last().innerText().catch(() => "")).slice(0, 900) });
  }
  await page.screenshot({ path: `${process.env.QA_SHOTS}/10c-after-1440.png` });
  r.save();
};

// 10d. Клиент: Кабинет → «Каталог» → поиск «Накладка».
scenarios["10d"] = async (browser) => {
  const r = new Report("10d");
  const { page } = await np(browser, 1440, { storageState: `${process.env.QA_OUT}/cab-state.json` });
  await page.goto(`${CAB}/catalog`);
  await page.waitForTimeout(3000);
  await settle(page);
  obs(r, "«Каталог» клиента", { sees: await seen(page, "main", 1500) });
  const search = page.getByPlaceholder(/Поиск|Найти/).first();
  if (await search.isVisible().catch(() => false)) { await search.fill("Накладка"); await page.waitForTimeout(2500); }
  obs(r, "поиск «Накладка»", { sees: await seen(page, "main", 1500) });
  await page.screenshot({ path: `${process.env.QA_SHOTS}/10d-catalog-1440.png` });
  r.save();
};
