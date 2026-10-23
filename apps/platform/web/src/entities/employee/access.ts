import type { Role } from "../../shared/api/generated/model";
import { rolesAccess, type RolesAccess } from "../role/roles";

/**
 * Что дают сотруднику выбранные роли — по матрицам ролей из `GET /admin/roles` (ADR-0012): объединение, как у BFF и CRM.
 * Неизвестные id (роль удалили, пока форма была открыта) пропускаются.
 */
export function accessOfRoleIds(roles: readonly Role[], ids: readonly string[]): RolesAccess {
  return rolesAccess(roles.filter((role) => ids.includes(role.id)));
}

/** Порядок ролей — как в списке ролей (системные первыми), не как их отметили. */
export function sortRoleIds(ids: readonly string[], roles: readonly Role[]): string[] {
  const order = roles.map((role) => role.id);
  return [...ids].sort((a, b) => order.indexOf(a) - order.indexOf(b));
}
