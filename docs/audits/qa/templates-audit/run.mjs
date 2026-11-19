// Продуктовый аудит «Документы · Шаблоны» (2026-11-20): обход вкладок и соседних экранов администратором на стенде.
// Запуск — как у прогона СЦ-2: QA_BASE, QA_OUT, QA_SHOTS, QA_COMPOSE; node docs/audits/qa/templates-audit/run.mjs
import { PANEL, Report, as, launch, obs, seen, settle, spaGoto } from "../sc2-walk/common.mjs";

const browser = await launch();
const r = new Report("tpl");
const page = await as(browser, r, "admin");
const shot = (name) => page.screenshot({ path: `${process.env.QA_SHOTS}/${name}.png` });
const body = async (max = 3500) => (await seen(page, "main", max));
const overlay = async () => (await page.locator(".ant-drawer:visible, [role=dialog]:visible").last().innerText().catch(() => "")).slice(0, 3000);

await settle(page);
await page.getByRole("link", { name: "Документы" }).first().click();
await page.waitForTimeout(1500);
obs(r, "меню «Документы»", { sees: (await page.locator("nav, aside").nth(1).innerText().catch(() => "")).replace(/\n/g, " | ") });
await page.getByRole("link", { name: "Шаблоны" }).first().click();
await page.waitForTimeout(2500);
await settle(page);
obs(r, "«Шаблоны» из меню «Документы»", { sees: `${page.url()}\n${await body()}` });
await shot("01-all");

for (const tab of ["documents", "letters", "emails", "quote"]) {
  await spaGoto(page, `/admin/templates?tab=${tab}`);
  await settle(page);
  await page.waitForTimeout(1200);
  obs(r, `вкладка ${tab}`, { sees: await body() });
  await shot(`02-${tab}`);
}

// Документы: образец, копия, создание.
await spaGoto(page, "/admin/templates?tab=documents");
await settle(page);
const firstOpen = page.getByRole("button", { name: /^(Просмотр|Открыть)/ }).first();
if (await firstOpen.isVisible().catch(() => false)) {
  await firstOpen.click();
  await page.waitForTimeout(3000);
  obs(r, "документы: образец открыт", { sees: await overlay() });
  await shot("03-doc-sample");
  await page.locator(".ant-drawer:visible .ant-drawer-title, [role=dialog]:visible").first().click().catch(() => {});
  await page.locator(".ant-drawer-close:visible, .ant-modal-close:visible").last().click().catch(() => {});
}
await page.getByRole("button", { name: "Создать шаблон" }).first().click().catch(() => {});
await page.waitForTimeout(2000);
obs(r, "документы: «Создать шаблон»", { sees: await overlay() });
await shot("04-doc-create");
await page.locator(".ant-drawer-close:visible, .ant-modal-close:visible").last().click().catch(() => {});

// Письма на бланке: встроенный шаблон.
await spaGoto(page, "/admin/templates?tab=letters");
await settle(page);
await page.getByRole("button", { name: /Открыть: Деловое письмо/ }).or(page.getByText("Деловое письмо")).first().click().catch(() => {});
await page.waitForTimeout(4000);
obs(r, "письма: «Деловое письмо»", { sees: (await overlay()) || (await body()) });
await shot("05-letter-open");
await page.locator(".ant-drawer-close:visible, .ant-modal-close:visible").last().click().catch(() => {});

// Почта: новое письмо.
await spaGoto(page, "/admin/templates?tab=emails");
await settle(page);
await page.getByRole("button").filter({ hasText: /Создать|Добавить|Новый/ }).first().click().catch(() => {});
await page.waitForTimeout(2000);
obs(r, "почта: форма нового шаблона", { sees: await overlay() });
await shot("06-email-create");
await page.locator(".ant-drawer-close:visible, .ant-modal-close:visible").last().click().catch(() => {});

// Соседние экраны.
for (const [name, path] of [["resolutions", "/admin/resolutions"], ["bot-templates", "/admin/telegram?tab=templates"], ["bot-texts", "/admin/telegram?tab=texts"], ["brand", "/admin/company?tab=brand"], ["numbering", "/admin/company?tab=numbering"], ["charges", "/admin/company?tab=charges"], ["company", "/admin/company"]]) {
  await spaGoto(page, path);
  await settle(page);
  await page.waitForTimeout(1500);
  obs(r, `соседний экран ${name}`, { sees: `${page.url()}\n${await body()}` });
  await shot(`07-${name}`);
}
// Где шаблон выбирают при работе: новое письмо и служебка.
for (const [name, path] of [["new-letter", "/eds/new?type=letter"], ["new-memo", "/eds/new?type=memo"]]) {
  await spaGoto(page, path);
  await settle(page);
  await page.waitForTimeout(1500);
  const text = await body(6000);
  obs(r, `форма ${name}: упоминания шаблона`, { sees: text.split("\n").filter((l) => /шаблон/i.test(l)).join(" | ") || "шаблон не упоминается" });
}
r.save();
await browser.close();
