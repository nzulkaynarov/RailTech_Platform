import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

import legacy from "./legacyMessageUsers.json";

const SRC = join(__dirname, "..", "..");
const LAYER = join("shared", "notify");

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "generated" ? [] : files(path);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

// `const { message } = App.useApp()` и подобное, а также `import { message | notification } from "antd"`.
const USES =
  /const\s*\{[^}]*\b(?:message|notification)\b[^}]*\}\s*=\s*App\.useApp\(\)|import\s*\{[^}]*\b(?:message|notification)\b[^}]*\}\s*from\s*"antd"/;

describe("единый слой уведомлений (УВЕД-1)", () => {
  const users = files(SRC)
    .map((path) => relative(SRC, path))
    .filter((path) => !path.startsWith(LAYER))
    .filter((path) => USES.test(readFileSync(join(SRC, path), "utf8")))
    .sort();

  it("antd message/notification вне shared/notify — только из списка прежних файлов; новых нет", () => {
    const fresh = users.filter((path) => !legacy.files.includes(path));
    expect(fresh, "используйте useNotify() из shared/notify/NotifyProvider").toEqual([]);
  });

  it("список прежних файлов только сокращается: перенесённый файл из него убирают", () => {
    const stale = legacy.files.filter((path) => !users.includes(path));
    expect(
      stale,
      "файл больше не обращается к antd message — уберите из legacyMessageUsers.json",
    ).toEqual([]);
  });
});
