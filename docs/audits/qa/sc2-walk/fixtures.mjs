// Файлы прогона СЦ-2: письмо налоговой (6), счёт перевозчика (7), спецификация клиента (8).
// Запуск: node docs/audits/qa/sc2-walk/fixtures.mjs <каталог> → SC2_TAX, SC2_COURIER, SC2_SPEC.
import { launch } from "../d26-gate/common.mjs";

const DOCS = {
  "tax-letter.pdf": `<p style="text-align:right">ГНИ Юнусабадского района г. Ташкента<br>исх. № 01-12/345 от 18.11.2026</p>
<p>Руководителю ООО «RailTech»</p><h3 style="text-align:center">Требование о представлении пояснений</h3>
<p>В ходе камеральной проверки декларации по НДС за октябрь 2026 года выявлены расхождения.
Просим в течение 5 рабочих дней представить пояснения и подтверждающие документы.</p><p>Начальник инспекции А. Каримов</p>`,
  "courier-invoice.pdf": `<h3>ООО «Быстрая доставка»</h3><p>Счёт № 77 от 19.11.2026</p>
<p>Доставка материалов по проекту PRJ-2026-001 — 1 500 000 сум, без НДС.</p><p>Оплата до 25.11.2026.</p>`,
  "spec.pdf": `<h3>Спецификация</h3><table border=1 cellpadding=6><tr><th>Позиция</th><th>Кол-во</th></tr>
<tr><td>Рельс Р65, длина 25 м</td><td>120 т</td></tr><tr><td>Накладка стыковая Р65</td><td>400 шт</td></tr></table>
<p>Доставка: Ташкент, ст. Сергели, до 15.12.2026.</p>`,
};

const dir = process.argv[2];
if (!dir) throw new Error("укажите каталог");
const browser = await launch();
const page = await browser.newPage();
for (const [name, body] of Object.entries(DOCS)) {
  await page.setContent(`<html><body style="font-family:serif;margin:48px">${body}</body></html>`);
  await page.pdf({ path: `${dir}/${name}`, format: "A4" });
}
await browser.close();
