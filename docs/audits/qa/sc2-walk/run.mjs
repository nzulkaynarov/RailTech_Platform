// СЦ-2: запуск сценариев прогона по именам (см. common.mjs).
import { launch } from "./common.mjs";
import { scenarios as s01 } from "./s01.mjs";
import { scenarios as s12 } from "./s12.mjs";
import { scenarios as s02 } from "./s02.mjs";
import { scenarios as s03 } from "./s03.mjs";
import { scenarios as s04 } from "./s04.mjs";
import { scenarios as s04b } from "./s04b.mjs";
import { scenarios as s05 } from "./s05.mjs";
import { scenarios as s06 } from "./s06.mjs";
import { scenarios as s07 } from "./s07.mjs";
import { scenarios as s08 } from "./s08.mjs";
import { scenarios as s09 } from "./s09.mjs";
import { scenarios as s10 } from "./s10.mjs";
import { scenarios as s11 } from "./s11.mjs";

const scenarios = { ...s01, ...s02, ...s03, ...s04, ...s04b, ...s05, ...s06, ...s07, ...s08, ...s09, ...s10, ...s11, ...s12 };
const browser = await launch();
for (const id of process.argv.slice(2)) {
  if (!scenarios[id]) throw new Error(`нет сценария ${id}`);
  console.log(`=== ${id}`);
  await scenarios[id](browser);
}
await browser.close();
