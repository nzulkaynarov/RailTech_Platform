import { MODULES, RESOURCES, type ModuleCode, type RoleCode } from "../../app/rbac.generated";

/**
 * Модули рейла по набору ролей — из сгенерированной матрицы (`platform-rbac.yaml`): модуль виден, если хотя бы один его
 * раздел не скрыт хотя бы одной из ролей (максимум по ролям, как у BFF). Руками матрица здесь не повторяется.
 */
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
