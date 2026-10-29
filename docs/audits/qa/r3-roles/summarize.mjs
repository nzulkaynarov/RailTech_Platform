// R-3: сводка результатов прогона: node summarize.mjs (QA_OUT — каталог с result-*.json)
import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
const OUT = process.env.QA_OUT;
let total = 0, fail = 0, scr = 0, noScroll = 0, axeClean = 0;
for (const f of readdirSync(OUT).filter((x) => /^result-.*\.json$/.test(x)).sort()) {
  const d = JSON.parse(readFileSync(resolve(OUT, f), "utf8"));
  const checks = d.rows.filter((r) => r.ok !== null);
  const bad = checks.filter((r) => r.ok === false);
  total += checks.length; fail += bad.length;
  for (const s of d.screens) { scr++; if (s.noHScroll) noScroll++; if (s.axe.length === 0) axeClean++; }
  console.log(`${f}: проверок ${checks.length}, не пройдено ${bad.length}, экранов×ширин ${d.screens.length}`);
  for (const b of bad) console.log(`   FAIL ${b.desc} :: ${b.detail.slice(0, 200)}`);
}
console.log(`\nИтого: проверок ${total}, не пройдено ${fail}; экранов×ширин ${scr}: без горизонтальной прокрутки ${noScroll}, axe 0 нарушений ${axeClean}`);
