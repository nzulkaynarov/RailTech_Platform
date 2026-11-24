import { describe, expect, it } from "vitest";

import { fitHidden } from "./fitColumns";

const WIDTH: Record<string, number> = { name: 300, kind: 160, unit: 160, vat: 160, docs: 130 };
const PRIORITY: Record<string, number> = { unit: 4, vat: 3, docs: 2 };
const widthOf = (id: string) => WIDTH[id] ?? 0;
const priorityOf = (id: string) => PRIORITY[id] ?? 0;
const IDS = ["name", "kind", "unit", "vat", "docs"];

describe("fitHidden", () => {
  it("ширина неизвестна (0): ничего не прячем", () => {
    expect(fitHidden(IDS, widthOf, priorityOf, 0)).toEqual([]);
  });

  it("помещается: ничего не прячем", () => {
    expect(fitHidden(IDS, widthOf, priorityOf, 910)).toEqual([]);
  });

  it("не помещается: уходят вторичные по убыванию приоритета, пока не поместится", () => {
    expect(fitHidden(IDS, widthOf, priorityOf, 800)).toEqual(["unit"]);
    expect(fitHidden(IDS, widthOf, priorityOf, 700)).toEqual(["unit", "vat"]);
  });

  it("столбцы без приоритета не прячутся, даже если не помещаются", () => {
    expect(fitHidden(IDS, widthOf, priorityOf, 100)).toEqual(["unit", "vat", "docs"]);
  });
});
