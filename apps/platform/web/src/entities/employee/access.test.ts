import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { parse } from "yaml";
import { describe, expect, it } from "vitest";

import { ERP_EXTRA_PERMISSIONS, ERP_ROLE_CODES, ROLES } from "../../app/rbac.generated";
import { erpAccessOfRoles, modulesOfRoles, sortRoles } from "./access";

interface Yaml {
  roles: Record<string, { erp_role_codes: string[]; erp_extra_permissions: string[] }>;
  resources: { key: string; module: string; access: Record<string, string> }[];
}
const matrix = parse(
  readFileSync(
    resolve(import.meta.dirname, "../../../../../../packages/contracts/platform-rbac.yaml"),
    "utf8",
  ),
) as Yaml;

const ORDER = ["dashboard", "crm", "eds", "erp", "chats", "admin"];

/** Эталон прямо из YAML: модуль виден, если хоть один его раздел не скрыт хоть одной из ролей. */
function expected(roles: string[]): string[] {
  const visible = new Set(
    matrix.resources
      .filter((r) => roles.some((role) => r.access[role] !== "hidden"))
      .map((r) => r.module),
  );
  return ORDER.filter((m) => visible.has(m));
}

describe("modulesOfRoles", () => {
  it.each(ROLES)("роль %s: модули как в platform-rbac.yaml", (role) => {
    expect(modulesOfRoles([role])).toEqual(expected([role]));
  });

  it("объединение ролей — максимум по матрице, порядок модулей рейла", () => {
    expect(modulesOfRoles(["ADMIN", "SUPPLY"])).toEqual(expected(["ADMIN", "SUPPLY"]));
    expect(modulesOfRoles(["ADMIN", "SUPPLY"])).toContain("admin");
    expect(modulesOfRoles([...ROLES])).toEqual(ORDER);
  });

  it("без ролей модулей нет", () => {
    expect(modulesOfRoles([])).toEqual([]);
  });

  it("только ADMIN: нет CRM и ERP, есть Admin", () => {
    expect(modulesOfRoles(["ADMIN"])).toEqual(["dashboard", "eds", "chats", "admin"]);
  });
});

describe("sortRoles", () => {
  it("порядок контракта, не порядок выбора", () => {
    expect(sortRoles(["ADMIN", "MANAGER", "SUPPLY"], ROLES)).toEqual([
      "MANAGER",
      "SUPPLY",
      "ADMIN",
    ]);
  });
});

describe("роли ERP из сгенерированной карты", () => {
  it.each(ROLES)("роль %s: erp_role_codes и права = platform-rbac.yaml", (role) => {
    expect([...ERP_ROLE_CODES[role]]).toEqual(matrix.roles[role]?.erp_role_codes);
    expect([...ERP_EXTRA_PERMISSIONS[role]]).toEqual(matrix.roles[role]?.erp_extra_permissions);
  });

  it("объединение без повторов в порядке ролей", () => {
    expect(erpAccessOfRoles(["SUPPLY", "ENGINEER"])).toEqual({
      admin: false,
      codes: ["CATALOG_SUPPLY", "FULFILLMENT"],
    });
    expect(erpAccessOfRoles(["ACCOUNTANT", "MANAGER"]).codes).toEqual(["VIEWER", "FINANCE"]);
  });

  it("ADMIN — суперпользователь ERP, остальные роли ERP не добавляют", () => {
    expect(erpAccessOfRoles(["ADMIN"])).toEqual({ admin: true, codes: [] });
    expect(erpAccessOfRoles(["SUPPLY", "ADMIN"])).toEqual({ admin: true, codes: [] });
  });

  it("без ролей ничего", () => {
    expect(erpAccessOfRoles([])).toEqual({ admin: false, codes: [] });
  });
});
