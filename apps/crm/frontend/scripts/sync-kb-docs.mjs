// Справка формата базы знаний (docs/kb) с W13-A5 живёт в Платформе: копия — apps/platform/web/src/generated/kb-docs,
// команда — `pnpm kb:sync` там же. Старый фронт CRM заморожен и удаляется в волне 13b; его копия src/generated/kb-docs
// остаётся как есть (тест kbDocs.test.ts сверяет её с docs/kb, пока docs/kb не менялся). Этот скрипт перенаправлен.
// Запуск: pnpm kb:sync
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const platform = join(here, "../../../platform/web/scripts/sync-kb-docs.mjs");
console.log(
  "kb-docs: синхронизация переведена в Платформу (apps/platform/web) — запускаю её скрипт",
);
const result = spawnSync(process.execPath, [platform], { stdio: "inherit" });
process.exit(result.status ?? 1);
