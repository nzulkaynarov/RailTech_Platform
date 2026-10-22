import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { parse } from "yaml";
import { describe, expect, it } from "vitest";

import { DEMO_USERS } from "./users";
import { MATRIX, MODULE_ORDER, RESTRICTED_FIELDS, ROLES, computeAccess } from "./rbac";

interface Yaml {
  roles: Record<string, { erp_role_codes: string[] }>;
  resources: { key: string; module: string; access: Record<string, string> }[];
  restricted_fields: Record<string, { visible_to: string[] }>;
}

const yaml = parse(
  readFileSync(
    resolve(import.meta.dirname, "../../../../../../packages/contracts/platform-rbac.yaml"),
    "utf8",
  ),
) as Yaml;

describe("фикстуры ролей = packages/contracts/platform-rbac.yaml", () => {
  it("те же шесть ролей", () => {
    expect([...ROLES].sort()).toEqual(Object.keys(yaml.roles).sort());
  });

  it("те же ресурсы, модули и уровни на каждую ячейку матрицы", () => {
    expect(Object.keys(MATRIX)).toEqual(yaml.resources.map((r) => r.key));
    for (const resource of yaml.resources) {
      const row = MATRIX[resource.key];
      expect(row?.module, resource.key).toBe(resource.module);
      for (const role of ROLES) {
        expect(row?.access[ROLES.indexOf(role)], `${resource.key} × ${role}`).toBe(
          resource.access[role],
        );
      }
    }
  });

  it("поля с ограничением совпадают", () => {
    for (const [name, field] of Object.entries(yaml.restricted_fields)) {
      expect([...(RESTRICTED_FIELDS[name] ?? [])].sort(), name).toEqual(
        [...field.visible_to].sort(),
      );
    }
    expect(Object.keys(RESTRICTED_FIELDS).sort()).toEqual(
      Object.keys(yaml.restricted_fields).sort(),
    );
  });

  it("модули в порядке рейла SPEC-v3 §6.1", () => {
    expect(MODULE_ORDER).toEqual(["dashboard", "crm", "eds", "erp", "chats", "admin"]);
  });

  it("доступ в ERP у ролей с erp_role_codes", () => {
    for (const role of ROLES) {
      expect(computeAccess([role]).access.erp, role).toBe(
        (yaml.roles[role]?.erp_role_codes.length ?? 0) > 0,
      );
    }
  });

  it("у одной роли модули — те, где есть непрятанный ресурс", () => {
    const expected: Record<string, string[]> = {
      MANAGER: ["dashboard", "crm", "eds", "erp", "chats"],
      DIRECTOR: ["dashboard", "crm", "eds", "erp", "chats", "admin"],
      SUPPLY: ["dashboard", "crm", "eds", "erp", "chats"],
      ENGINEER: ["dashboard", "crm", "eds", "erp", "chats"],
      ACCOUNTANT: ["dashboard", "crm", "eds", "erp", "chats"],
      ADMIN: ["dashboard", "eds", "chats", "admin"],
    };
    for (const role of ROLES) expect(computeAccess([role]).modules, role).toEqual(expected[role]);
  });

  it("объединение ролей берёт максимум: менеджер + директор видят разделы обеих", () => {
    const merged = computeAccess(["MANAGER", "DIRECTOR"]);
    expect(merged.resources["crm.leads"]).toBe("full");
    expect(merged.resources["eds.inbox"]).toBe("full");
    expect(merged.resources["dashboard.summary"]).toBe("full");
    expect(merged.resources["erp.calc"]).toBe("full");
  });

  it("скрытые разделы в resources не перечисляются", () => {
    const manager = computeAccess(["MANAGER"]);
    expect(manager.resources).not.toHaveProperty("admin");
    expect(manager.resources).not.toHaveProperty("erp.calc");
    expect(manager.resources["erp.stock"]).toBe("read");
  });

  it("демо-пользователи: шесть ролей по одному, один универсал, адреса зарезервированного домена", () => {
    const single = DEMO_USERS.filter(
      (u) => u.roles.length === 1 && !u.loginError && !u.mustChangePassword,
    );
    expect(new Set(single.flatMap((u) => u.roles))).toEqual(new Set(ROLES));
    expect(DEMO_USERS.some((u) => u.roles.length === ROLES.length)).toBe(true);
    for (const user of DEMO_USERS) expect(user.email).toMatch(/@demo\.example$/);
  });
});
