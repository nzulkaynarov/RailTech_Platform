import {
  ERP_ROLE_CODES,
  MODULES,
  RESOURCES,
  ROLES,
  type ModuleCode,
  type RoleCode,
} from "../../app/rbac.generated";

/**
 * Модули рейла по набору ролей — из сгенерированной матрицы (`platform-rbac.yaml`): модуль виден, если хотя бы один его
 * раздел не скрыт хотя бы одной из ролей (максимум по ролям, как у BFF). Руками матрица здесь не повторяется.
 */
const ROLE_ORDER: readonly RoleCode[] = ROLES;

export function modulesOfRoles(roles: readonly RoleCode[]): ModuleCode[] {
  const visible = new Set<ModuleCode>();
  for (const resource of Object.values(RESOURCES)) {
    if (roles.some((role) => resource.access[role] !== "hidden")) visible.add(resource.module);
  }
  return MODULES.filter((module) => visible.has(module));
}

/** Порядок ролей — как в контракте, не как их отметили. */
export function sortRoles<T extends RoleCode>(
  roles: readonly T[],
  order: readonly RoleCode[],
): T[] {
  return [...roles].sort((a, b) => order.indexOf(a) - order.indexOf(b));
}

/**
 * Что CRM выдаст в ERP набору ролей Платформы — из сгенерированной карты `erp_role_codes`: объединение ролей ERP по
 * порядку ролей; ADMIN — суперпользователь ERP (роли ERP ему не нужны, остальные роли в ERP не добавляют ничего).
 */
// TODO(ADR-0012): карта роль Платформы -> роли ERP (`ERP_ROLE_CODES`) и особый случай `ADMIN` заменить на данные роли
// из `/admin/roles` (права ERP вычисляются из матрицы возможностей); здесь останутся только ADMIN и DIRECTOR.
export function erpAccessOfRoles(roles: readonly RoleCode[]): { admin: boolean; codes: string[] } {
  if (roles.includes("ADMIN")) return { admin: true, codes: [] };
  const codes: string[] = [];
  for (const role of ROLE_ORDER) {
    if (!roles.includes(role)) continue;
    for (const code of ERP_ROLE_CODES[role]) if (!codes.includes(code)) codes.push(code);
  }
  return { admin: false, codes };
}
