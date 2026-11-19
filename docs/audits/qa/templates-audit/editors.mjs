// Аудит «Шаблоны»: редакторы — образец договора, новый шаблон документа, новое письмо почты, «Бланк и бренд».
import { Report, as, launch, obs, seen, settle, spaGoto } from "../sc2-walk/common.mjs";

const browser = await launch();
const r = new Report("tpl-editors");
const page = await as(browser, r, "admin");
const shot = (name) => page.screenshot({ path: `${process.env.QA_SHOTS}/${name}.png` });
const overlay = async () => (await page.locator(".ant-drawer:visible, [role=dialog]:visible").last().innerText().catch(() => "")).slice(0, 3500);
const close = async () => { await page.locator(".ant-drawer-close:visible, .ant-modal-close:visible").last().click().catch(() => {}); await page.waitForTimeout(600); };

for (const [n, name] of [["11", "Договор поставки"], ["12", "Счёт на оплату"], ["13", "Гарантийное письмо"]]) {
  await spaGoto(page, "/admin/templates?tab=documents");
  await settle(page);
  await page.getByRole("link", { name: new RegExp(name) }).or(page.getByRole("button", { name: new RegExp(name) })).first().click();
  await page.waitForTimeout(4000);
  obs(r, `образец «${name}»`, { sees: (await overlay()) || (await seen(page, "main", 3000)) });
  await shot(`${n}-doc-${n}`);
  await close();
}
await spaGoto(page, "/admin/templates?tab=documents");
await settle(page);
await page.getByRole("button", { name: "Создать шаблон" }).click();
await page.waitForTimeout(2500);
obs(r, "новый шаблон документа", { sees: (await overlay()) || (await seen(page, "main", 3000)) });
await shot("14-doc-create");
await close();

await spaGoto(page, "/admin/templates?tab=emails");
await settle(page);
await page.getByRole("button", { name: "Создать шаблон письма" }).click();
await page.waitForTimeout(2500);
obs(r, "новый шаблон письма почты", { sees: (await overlay()) || (await seen(page, "main", 3000)) });
await shot("15-email-create");
await close();

await spaGoto(page, "/admin/company?tab=brand");
await settle(page);
await page.waitForTimeout(2500);
obs(r, "«Бланк и бренд»", { sees: `${page.url()}\n${await seen(page, "main", 4000)}` });
await shot("16-brand-top");
await page.mouse.wheel(0, 900);
await page.waitForTimeout(1500);
await shot("17-brand-bottom");
r.save();
await browser.close();
