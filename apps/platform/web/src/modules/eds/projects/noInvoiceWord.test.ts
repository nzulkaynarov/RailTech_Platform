import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Свои PDF (счёт, акт, договор) никогда не называются «счёт-фактурой» (SPEC-v3 §2.4): это налоговый документ,
 * который платформа не выпускает. Ни в интерфейсе (ru/uz/en), ни в названиях файлов, ни в моках раздела такого слова нет.
 */
const WORD = /фактур|faktur|tax[\s-]*invoice|vat[\s-]*invoice/i;

const ROOT = join(import.meta.dirname, "..", "..", "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.(tsx?|css)$/.test(entry.name) && entry.name !== "noInvoiceWord.test.ts" ? [path] : [];
  });
}

describe("слово «счёт-фактура» в собственных документах проекта", () => {
  it.each(["ru", "uz", "en"])("тексты %s: слова нет", (lang) => {
    const text = readFileSync(join(ROOT, "shared", "i18n", lang, "projects.json"), "utf8");
    expect(text).not.toMatch(WORD);
  });

  it("код раздела, имена файлов и моки: слова нет", () => {
    const files = [
      ...sourceFiles(join(ROOT, "modules", "eds", "projects")),
      join(ROOT, "mocks", "edsProjects.ts"),
      join(ROOT, "mocks", "fixtures", "projects.ts"),
    ];
    expect(files.length).toBeGreaterThan(10);
    for (const file of files) {
      expect(readFileSync(file, "utf8"), file).not.toMatch(WORD);
    }
  });
});
