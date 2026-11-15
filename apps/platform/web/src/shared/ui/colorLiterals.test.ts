import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { expect, it } from "vitest";

/**
 * Стандарт интерфейса §2 (docs/architecture/ui-standard.md): цвета в CSS — только переменные токенов `var(--rt-color-…)`.
 * Литерал цвета в стилях модуля возвращает разнобой и не меняется вместе с палитрой.
 */
function cssFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return cssFiles(path);
    return entry.name.endsWith(".css") && !entry.name.includes(".generated.") ? [path] : [];
  });
}

it("в CSS нет литералов цвета", () => {
  const found: string[] = [];
  for (const file of cssFiles(join(process.cwd(), "src"))) {
    const code = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    code.split("\n").forEach((line, index) => {
      if (/#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b/.test(line)) {
        found.push(`${file.replace(process.cwd(), "")}:${String(index + 1)} ${line.trim()}`);
      }
    });
  }
  expect(found).toEqual([]);
});
