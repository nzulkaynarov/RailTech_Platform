// QA-P1: свод результатов прогона (QA_OUT/result-*.json) — для отчёта: проверки по сценариям и таблица экранов (1440/1280/390).
//   QA_OUT=<каталог> node docs/runbooks/qa/plt-p1/summarize.mjs
import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const OUT = process.env.QA_OUT ?? "/tmp/qa-p1-out";
const files = readdirSync(OUT).filter((f) => /^result-s\d+\.json$/.test(f)).sort((a, b) => Number(a.match(/\d+/)[0]) - Number(b.match(/\d+/)[0]));
let screens = 0, overflow = 0, axe = 0, checks = 0, failed = 0;
for (const f of files) {
  const d = JSON.parse(readFileSync(resolve(OUT, f), "utf8"));
  const id = f.replace(/^result-|\.json$/g, "");
  const rows = d.rows.filter((r) => r.ok !== null && !/@\d+: (без горизонтальной|axe)/.test(r.desc));
  const bad = rows.filter((r) => r.ok === false);
  checks += rows.length;
  failed += bad.length;
  console.log(`\n## ${id}: проверок ${rows.length}, не пройдено ${bad.length}`);
  for (const r of bad) console.log(`  FAIL ${r.desc} :: ${r.detail}`);
  for (const s of d.screens) {
    screens++;
    if (!s.noHScroll) overflow++;
    if (s.axe.length) axe++;
  }
  console.log(`  экранов×ширин: ${d.screens.length}; с горизонтальной прокруткой: ${d.screens.filter((s) => !s.noHScroll).length}; с нарушениями axe: ${d.screens.filter((s) => s.axe.length).length}`);
  for (const s of d.screens.filter((x) => x.axe.length || !x.noHScroll)) console.log(`  ! ${s.file}: scrollWidth=${s.scrollWidth}; axe=${s.axe.join(" ;; ")}`);
}
console.log(`\nИТОГО: проверок ${checks}, не пройдено ${failed}; экранов×ширин ${screens}, с прокруткой ${overflow}, с нарушениями axe ${axe}`);
