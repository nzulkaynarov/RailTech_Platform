import { describe, expect, it } from "vitest";

import type { EmployeeCapabilities } from "../../shared/api/generated/model";
import { areaLevel, fitItems, ITEMS_MAX, LINE_MAX, soft, summaryItems } from "./areas";

const text = (ru: string) => ({ ru, uz: ru, en: ru });
const row = (key: string, level: string) =>
  ({
    key,
    name: text(key),
    level,
    partial: false,
    levels: [],
    from_roles: [],
    others: [],
    others_total: 0,
  }) as never;

describe("область: высший уровень", () => {
  const cell = (level: string) => ({ level }) as never;
  it("берётся самый высокий из возможностей области", () => {
    expect(areaLevel([cell("view"), cell("decide"), cell("work")])).toBe("decide");
    expect(areaLevel([cell("none"), cell("none")])).toBe("none");
    expect(areaLevel([])).toBe("none");
  });
});

describe("название в середине фразы", () => {
  it("первая буква строчная, сокращения целы", () => {
    expect(soft("Лиды и клиенты")).toBe("лиды и клиенты");
    expect(soft("КП и договор")).toBe("КП и договор");
  });
});

describe("сводка по областям", () => {
  const data = {
    zones_known: true,
    zones: [{ id: "1", name: text("Продажи") }],
    groups: [
      {
        key: "a",
        name: text("Лиды и клиенты"),
        step: text("1"),
        rows: [row("Лиды", "work"), row("Почта", "work")],
      },
      {
        key: "b",
        name: text("Оплата и документы"),
        step: text("2"),
        rows: [row("Счета", "none"), row("Оплаты", "none")],
      },
      {
        key: "c",
        name: text("КП и договор"),
        step: text("3"),
        rows: [row("КП", "decide"), row("Договор", "view")],
      },
    ],
  } as unknown as EmployeeCapabilities;

  it("область целиком называется областью, частичная — своими возможностями", () => {
    const lines = Object.fromEntries(summaryItems(data, "ru").map((l) => [l.key, l.items]));
    expect(lines["does"]).toEqual(["лиды и клиенты", "КП"]);
    expect(lines["decides"]).toEqual(["КП"]);
    expect(lines["responsible"]).toEqual(["продажи"]);
    expect(lines["lacks"]).toEqual(["оплата и документы"]);
  });

  it("строка не длиннее 90 знаков и шести названий; остаток — «и ещё N»", () => {
    const many = Array.from({ length: 12 }, (_, i) => `возможность номер ${String(i)}`);
    const { shown, hidden } = fitItems("Ведёт", many, (n) => `и ещё ${String(n)}`);
    expect(shown.length).toBeLessThanOrEqual(ITEMS_MAX);
    expect(hidden).toBe(many.length - shown.length);
    expect(`Ведёт: ${shown.join(", ")} и ещё ${String(hidden)}.`.length).toBeLessThanOrEqual(
      LINE_MAX,
    );
  });

  it("одно очень длинное название всё равно показывается", () => {
    const { shown } = fitItems("Ведёт", ["x".repeat(120)], (n) => String(n));
    expect(shown).toHaveLength(1);
  });
});
