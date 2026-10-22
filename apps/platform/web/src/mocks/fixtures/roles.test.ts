import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { parse } from "yaml";
import { describe, expect, it } from "vitest";

import { ROLE_ID, computeAccess, seedRoles } from "./roles";

interface CatalogRole {
  name: { ru: string };
  access: Record<string, string>;
  restricted_fields: string[];
}
const spec = parse(
  readFileSync(
    resolve(import.meta.dirname, "../../../../../../packages/contracts/platform-rbac.yaml"),
    "utf8",
  ),
) as { system_roles: Record<string, CatalogRole>; templates: Record<string, CatalogRole> };

describe("роли MSW = системные роли и шаблоны каталога (как CRM при первом запуске)", () => {
  it("шесть ролей с id 1–6: две системные с кодом, четыре из шаблонов `tpl:`", () => {
    const roles = seedRoles();
    expect(roles.map((r) => [r.id, r.code, r.system])).toEqual([
      ["1", "ADMIN", true],
      ["2", "DIRECTOR", true],
      ["3", "tpl:MANAGER", false],
      ["4", "tpl:SUPPLY", false],
      ["5", "tpl:ENGINEER", false],
      ["6", "tpl:ACCOUNTANT", false],
    ]);
    expect(ROLE_ID.ACCOUNTANT).toBe("6");
  });

  it("матрицы, поля и названия — из platform-rbac.yaml", () => {
    for (const role of seedRoles()) {
      const code = role.demo ?? "";
      const source = spec.system_roles[code] ?? spec.templates[code];
      expect(role.access, code).toEqual(source?.access);
      expect([...role.restricted_fields].sort(), code).toEqual(
        [...(source?.restricted_fields ?? [])].sort(),
      );
      expect(role.name).toBe(source?.name.ru);
    }
  });

  it("объединение ролей сотрудника — как у BFF", () => {
    const [admin, director, manager, , , accountant] = seedRoles();
    if (!admin || !director || !manager || !accountant) throw new Error("нет предустановок");
    expect(computeAccess([manager, accountant]).modules).toEqual([
      "dashboard",
      "crm",
      "eds",
      "erp",
      "chats",
    ]);
    expect(computeAccess([admin]).resources).toEqual(admin.access);
    expect(computeAccess([director, accountant]).restricted_fields).toEqual([
      "cost_margin",
      "supplier_prices",
      "totals_only",
    ]);
  });
});
