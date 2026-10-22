import { describe, expect, it } from "vitest";

import {
  DOC_SPECS,
  type DocKind,
  docNumberToPath,
  formatDocNumber,
  isDocNumber,
  parseDocNumber,
  projectNumberOf,
} from "./docNumber";

// Примеры из SPEC-v3 §2.2
const EXAMPLES: [DocKind, string][] = [
  ["lead", "L-2041"],
  ["incoming", "ВХ-104/26"],
  ["request", "ЗВ-2026-104"],
  ["project", "ПР-2026-104"],
  ["quote", "КП-2026/115"],
  ["outgoing", "ИСХ-082/26"],
  ["contract", "ДОГ-2026/104"],
  ["invoice", "СЧ-2026/142"],
  ["act", "АКТ-2026/058"],
  ["memo", "СЗ-2026/031"],
  ["supplierOrder", "ЗП-2026-031"],
];

describe("номера SPEC-v3 §2.2", () => {
  it.each(EXAMPLES)("%s: разбор и сборка обратимы (%s)", (kind, text) => {
    const parts = parseDocNumber(text);
    expect(parts?.kind).toBe(kind);
    expect(parts && formatDocNumber(parts)).toBe(text);
  });

  it("покрыты все виды", () => {
    expect(EXAMPLES.map(([kind]) => kind).sort()).toEqual(Object.keys(DOC_SPECS).sort());
  });

  it("части номера", () => {
    expect(parseDocNumber("ВХ-104/26")).toEqual({ kind: "incoming", year: 2026, seq: 104 });
    expect(parseDocNumber("ЗВ-2026-104")).toEqual({ kind: "request", year: 2026, seq: 104 });
    expect(parseDocNumber("L-2041")).toEqual({ kind: "lead", seq: 2041 });
  });

  it("версия КП", () => {
    expect(parseDocNumber("КП-2026/115 v2")).toEqual({
      kind: "quote",
      year: 2026,
      seq: 115,
      version: 2,
    });
    expect(formatDocNumber({ kind: "quote", year: 2026, seq: 115, version: 2 })).toBe(
      "КП-2026/115 v2",
    );
    expect(formatDocNumber({ kind: "quote", year: 2026, seq: 115 })).toBe("КП-2026/115");
  });

  it("порядковый номер дополняется нулями", () => {
    expect(formatDocNumber({ kind: "memo", year: 2026, seq: 5 })).toBe("СЗ-2026/005");
    expect(formatDocNumber({ kind: "lead", seq: 7 })).toBe("L-0007");
    expect(formatDocNumber({ kind: "incoming", year: 2026, seq: 1 })).toBe("ВХ-001/26");
  });

  it("не номера", () => {
    for (const text of [
      "",
      "ЗВ-26-104",
      "ЗВ-2026/104",
      "ПР-2026-10",
      "КП-2026-115",
      "LEAD-1",
      "ЗВ-2026-104 v2",
    ]) {
      expect(isDocNumber(text), text).toBe(false);
    }
  });

  it("проект наследует номер заявки", () => {
    expect(projectNumberOf("ЗВ-2026-104")).toBe("ПР-2026-104");
    expect(projectNumberOf("ПР-2026-104")).toBeNull();
    expect(projectNumberOf("что-то")).toBeNull();
  });

  it("в адресе номер кодируется", () => {
    expect(docNumberToPath("ПР-2026-104")).toBe("%D0%9F%D0%A0-2026-104");
    expect(docNumberToPath("ВХ-104/26")).toBe("%D0%92%D0%A5-104%2F26");
  });
});
