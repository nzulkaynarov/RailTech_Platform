import { http, HttpResponse } from "msw";

import { ROLE_ID, type PresetCode, roleRefOf, seedRoles, toRole } from "../mocks/fixtures/roles";
import type { Role, RoleRef } from "../shared/api/generated/model";

/** Роли компании для тестов компонентов без сессии мока: системные и шаблоны каталога (id 1–6). */
export function companyRoles(extra: Role[] = []): Role[] {
  return [...seedRoles().map((role) => toRole(role, 0)), ...extra];
}

export function rolesHandler(extra: Role[] = []) {
  return http.get("*/admin/roles", () => HttpResponse.json({ items: companyRoles(extra) }));
}

/** Ссылка на роль-предустановку, как её отдаёт BFF в `Employee.roles` и `Me.roles`. */
export function ref(code: PresetCode): RoleRef {
  const role = seedRoles().find((r) => r.id === ROLE_ID[code]);
  if (!role) throw new Error(code);
  return roleRefOf(role);
}

export { ROLE_ID };
