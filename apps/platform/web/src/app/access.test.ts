import { describe, expect, it } from "vitest";

import type { Me } from "../shared/api/generated/model";
import { canEdit, canSee, levelForRule } from "./access";

const me = {
  resources: { "crm.clients": "read", "crm.leads": "full", admin: "read" },
} as unknown as Me;

describe("доступ по Me.resources", () => {
  it("скрытый ресурс — нет в resources", () => {
    expect(canSee(me, { resource: "eds.inbox" })).toBe(false);
  });

  it("уровень ресурса и правило «любой из» берут максимум", () => {
    expect(levelForRule(me, { resource: "crm.clients" })).toBe("read");
    expect(levelForRule(me, { anyOf: ["crm.clients", "crm.leads"] })).toBe("full");
    expect(levelForRule(me, { anyOf: ["eds.inbox", "erp.calc"] })).toBeUndefined();
  });

  it("раздел с level: full не виден при чтении (Admin · Журнал интеграций)", () => {
    expect(canSee(me, { resource: "admin" })).toBe(true);
    expect(canSee(me, { resource: "admin", level: "full" })).toBe(false);
    expect(canSee(me, { resource: "crm.leads", level: "full" })).toBe(true);
    expect(canSee(me, { anyOf: ["crm.clients", "crm.leads"], level: "full" })).toBe(true);
  });

  it("запись — только при full", () => {
    expect(canEdit(me, "crm.leads")).toBe(true);
    expect(canEdit(me, "crm.clients")).toBe(false);
    expect(canEdit(me, "erp.calc")).toBe(false);
  });
});
