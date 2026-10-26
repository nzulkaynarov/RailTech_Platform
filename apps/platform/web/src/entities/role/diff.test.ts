import { describe, expect, it } from "vitest";

import type { RoleSnapshot } from "../../shared/api/generated/model";
import { isEmptyDiff, roleDiff } from "./diff";

const snap = (over: Partial<RoleSnapshot> = {}): RoleSnapshot => ({
  name: "Закупки",
  description: "",
  access: {},
  restricted_fields: [],
  ...over,
});

describe("roleDiff", () => {
  it("уровни разделов: получил, потерял, повысил — в порядке каталога", () => {
    const diff = roleDiff(
      snap({ access: { "erp.calc": "read", "crm.leads": "full" } }),
      snap({ access: { "erp.calc": "full", "chats.internal": "read" } }),
    );

    expect(diff.sections).toEqual([
      { resource: "crm.leads", from: "full" },
      { resource: "erp.calc", from: "read", to: "full" },
      { resource: "chats.internal", to: "read" },
    ]);
  });

  it("название, описание и поля с ограничением", () => {
    const diff = roleDiff(
      snap({ restricted_fields: ["cost_margin"] }),
      snap({ name: "Снабжение", description: "Новое", restricted_fields: ["supplier_prices"] }),
    );

    expect(diff.name).toEqual({ from: "Закупки", to: "Снабжение" });
    expect(diff.description).toBe(true);
    expect(diff.fields).toEqual([
      { field: "cost_margin", visible: false },
      { field: "supplier_prices", visible: true },
    ]);
  });

  it("без изменений — пустое", () => {
    expect(isEmptyDiff(roleDiff(snap(), snap()))).toBe(true);
  });

  it("создание: всё из «после»", () => {
    const diff = roleDiff(undefined, snap({ access: { "erp.calc": "read" } }));
    expect(diff.sections).toEqual([{ resource: "erp.calc", to: "read" }]);
    expect(diff.name).toBeUndefined();
  });
});
