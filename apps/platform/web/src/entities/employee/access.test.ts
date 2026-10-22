import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { parse } from "yaml";
import { describe, expect, it } from "vitest";

import { ROLES } from "../../app/rbac.generated";
import { modulesOfRoles, sortRoles } from "./access";

interface Yaml {
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
