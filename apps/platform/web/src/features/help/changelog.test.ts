import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { CHANGELOG, LATEST_WHATS_NEW, entryDate, isNewer, parseEntry } from "./changelog";

const SOURCE = join(import.meta.dirname, "../../../../../../docs/kb/help/changelog");

describe("«Что нового» в сборке (W-REL)", () => {
  it("совпадает с docs/kb/help/changelog (источник правды); обновить — `pnpm kb:sync`", () => {
    const files = readdirSync(SOURCE).filter((name) => name.endsWith(".md"));
    expect(CHANGELOG).toHaveLength(files.length);
    for (const name of files) {
      const expected = parseEntry(
        name.replace(/\.md$/, ""),
        readFileSync(join(SOURCE, name), "utf-8"),
      );
      expect(CHANGELOG.find((entry) => entry.date === expected.date)).toEqual(expected);
    }
  });

  it("имя файла — дата записи; новые сверху; у каждой записи заголовок и пункты", () => {
    for (const name of readdirSync(SOURCE).filter((file) => file.endsWith(".md"))) {
      const entry = parseEntry(name, readFileSync(join(SOURCE, name), "utf-8"));
      expect(`${entry.date}.md`).toBe(name);
      expect(entry.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(entry.title).not.toBe(entry.date);
      expect(entry.items.length).toBeGreaterThan(0);
    }
    const dates = CHANGELOG.map((entry) => entry.date);
    expect(dates).toEqual([...dates].sort().reverse());
    expect(LATEST_WHATS_NEW).toBe(dates[0]);
  });
});

describe("parseEntry", () => {
  it("пункт с ролями, «Все» и без пометки — для всех", () => {
    const entry = parseEntry(
      "x",
      "---\ndate: 2026-11-02\ntitle: Склад\n---\n- **Снабженец, директор:** Остатки в Платформе.\n- **Все:** Быстрее поиск.\n- Без пометки.\n\nНе пункт.",
    );
    expect(entry).toEqual({
      date: "2026-11-02",
      title: "Склад",
      items: [
        { roles: ["Снабженец", "директор"], text: "Остатки в Платформе." },
        { roles: [], text: "Быстрее поиск." },
        { roles: [], text: "Без пометки." },
      ],
    });
  });
});

describe("isNewer", () => {
  it("null — ничего не видел; меньше — есть новое; поле не пришло или записей нет — не показываем", () => {
    expect(isNewer(null, "2026-10-28")).toBe(true);
    expect(isNewer("2026-10-01", "2026-10-28")).toBe(true);
    expect(isNewer("2026-10-28", "2026-10-28")).toBe(false);
    expect(isNewer(undefined, "2026-10-28")).toBe(false);
    expect(isNewer(null, undefined)).toBe(false);
  });

  it("дата записи словами на языке интерфейса", () => {
    expect(entryDate("2026-10-28", "ru")).toBe("28 октября 2026 г.");
    expect(entryDate("2026-10-28", "en")).toBe("October 28, 2026");
    expect(entryDate("не-дата", "ru")).toBe("не-дата");
  });
});
