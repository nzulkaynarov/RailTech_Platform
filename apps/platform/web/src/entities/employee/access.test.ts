import { describe, expect, it } from "vitest";

import { seedRoles, toRole } from "../../mocks/fixtures/roles";
import type { Role } from "../../shared/api/generated/model";
import { accessOfRoleIds, sortRoleIds } from "./access";

const roles: Role[] = [
  ...seedRoles().map((role) => toRole(role, 0)),
  {
    id: "41",
    name: "Менеджер и бухгалтер",
    description: "",
    system: false,
    access: { "crm.leads": "full", "eds.payments": "full" },
    restricted_fields: ["totals_only"],
    employees: 0,
    updated_at: "2026-10-23T09:00:00Z",
  },
];

describe("accessOfRoleIds — по матрицам ролей (ADR-0012)", () => {
  it("созданная роль: ровно её модули; ERP — по разделу «Счета и оплаты»", () => {
    const access = accessOfRoleIds(roles, ["41"]);
    expect(access.modules).toEqual(["crm", "eds"]);
    expect(access.erp).toBe(true);
    expect(access.systemAdmin).toBe(false);
    expect(access.adminWithoutSystem).toBe(false);
  });

  it("объединение ролей — максимум по разделу, модули в порядке рейла", () => {
    const access = accessOfRoleIds(roles, ["4", "1"]);
    expect(access.modules).toEqual(["dashboard", "crm", "eds", "erp", "chats", "admin"]);
    expect(access.access["erp.calc"]).toBe("full");
    expect(access.systemAdmin).toBe(true);
  });

  it("системная роль «Администратор» — полный администратор; без ролей — ничего", () => {
    expect(accessOfRoleIds(roles, ["1"]).modules).toEqual(["dashboard", "eds", "chats", "admin"]);
    expect(accessOfRoleIds(roles, []).modules).toEqual([]);
    expect(accessOfRoleIds(roles, ["999"]).modules).toEqual([]);
  });

  it("Admin «полный» в созданной роли без системной — отдельное предупреждение", () => {
    const custom: Role = {
      id: "42",
      name: "Офис-менеджер",
      description: "",
      system: false,
      access: { admin: "full" },
      restricted_fields: [],
      employees: 0,
      updated_at: "2026-10-23T09:00:00Z",
    };
    expect(accessOfRoleIds([...roles, custom], ["42"]).adminWithoutSystem).toBe(true);
    expect(accessOfRoleIds([...roles, custom], ["42", "1"]).adminWithoutSystem).toBe(false);
  });
});

describe("sortRoleIds", () => {
  it("порядок списка ролей, не порядок выбора", () => {
    expect(sortRoleIds(["41", "1", "3"], roles)).toEqual(["1", "3", "41"]);
  });
});
