// Копирует docs/kb/{FORMAT,PROMPT,example}.md в src/generated/kb-docs (M5-CRM-02, с W13-A5 — для Платформы)
// и статьи помощи docs/kb/help/*.md в src/generated/help-articles (W15-H7), записи «Что нового» docs/kb/help/changelog/*.md —
// в src/generated/help-articles/changelog (W-REL).
// Источник правды — docs/kb в корне репозитория; контекст Docker-сборки web — только apps/platform/web,
// поэтому копия лежит в репозитории, а тест src/modules/crm/kb/kbDocs.test.ts следит за равенством.
// Запуск: pnpm kb:sync (или make -C apps/platform kb-sync из корня репозитория).
import { copyFileSync, mkdirSync, readdirSync, rmSync } from "node:fs";
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

// Статьи помощи сотрудникам (W15-H7): docs/kb/help/*.md -> src/generated/help-articles. Каталог пересоздаётся целиком, чтобы
// удалённая статья не оставалась в сборке; равенство проверяет src/features/help/articles.test.ts.
const helpSource = join(source, "help");
const helpTarget = join(here, "../src/generated/help-articles");
rmSync(helpTarget, { recursive: true, force: true });
mkdirSync(helpTarget, { recursive: true });
for (const name of readdirSync(helpSource).filter((file) => file.endsWith(".md"))) {
  copyFileSync(join(helpSource, name), join(helpTarget, name));
}
console.log(`help-articles: скопировано в ${helpTarget}`);

// «Что нового» (W-REL): docs/kb/help/changelog/<дата>.md -> src/generated/help-articles/changelog; равенство проверяет
// src/features/help/changelog.test.ts. Каталог пересоздан выше вместе со статьями.
const changelogSource = join(helpSource, "changelog");
const changelogTarget = join(helpTarget, "changelog");
mkdirSync(changelogTarget, { recursive: true });
for (const name of readdirSync(changelogSource).filter((file) => file.endsWith(".md"))) {
  copyFileSync(join(changelogSource, name), join(changelogTarget, name));
}
console.log(`changelog: скопировано в ${changelogTarget}`);
