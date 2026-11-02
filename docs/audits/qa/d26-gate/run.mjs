// D2-6: сценарии гейта D2 (путь от резолюции до «Выполнено») против живого стенда `rt-gate-d26`.
// Запуск из корня worktree:
//   QA_BASE=http://platform.localhost:8101 QA_OUT=<каталог вне репозитория> QA_COMPOSE="<docker compose -p rt-gate-d26 …>" node docs/audits/qa/d26-gate/run.mjs <сценарии>
// Пароли генерируются на лету и лежат только в QA_OUT/state.json (вне репозитория).
import { launch } from "./common.mjs";
import { scenarios as base } from "./sc-base.mjs";
import { scenarios as path } from "./sc-path.mjs";
import { scenarios as extra } from "./sc-extra.mjs";
import { scenarios as cab } from "./sc-cab.mjs";

const scenarios = { ...base, ...path, ...extra, ...cab };
const only = process.argv.slice(2);
const browser = await launch();
for (const id of only) {
  if (!scenarios[id]) throw new Error(`нет сценария ${id}`);
  console.log(`=== ${id}`);
  await scenarios[id](browser);
}
await browser.close();
