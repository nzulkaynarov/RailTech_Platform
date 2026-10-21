// Копирует docs/kb/{FORMAT,PROMPT,example}.md в src/generated/kb-docs (M5-CRM-02).
// Источник правды — docs/kb в корне репозитория; контекст Docker-сборки фронтенда — только
// apps/crm/frontend, поэтому копия лежит в репозитории, а тест kbDocs.test.ts следит за равенством.
// Запуск: pnpm kb:sync
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, "../../../../docs/kb");
const target = join(here, "../src/generated/kb-docs");
mkdirSync(target, { recursive: true });
for (const name of ["FORMAT.md", "PROMPT.md", "example.md"]) {
  copyFileSync(join(source, name), join(target, name));
}
console.log(`kb-docs: скопировано в ${target}`);
