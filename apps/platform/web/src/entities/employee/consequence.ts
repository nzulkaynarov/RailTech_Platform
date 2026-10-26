import type { TFunction } from "i18next";

import type { RolesAccess } from "../role/roles";

/**
 * Строки «Что произойдёт» про права в бэкендах из матрицы выбранных ролей (ADR-0012, R-1, R3-D-2): системная роль
 * «Администратор» — суперпользователь ERP (до C2), в CRM — раздел `admin` каталога (без лидов, клиентов, сделок); раздел
 * Admin «полный» в созданной роли суперпользователя ERP не даёт (Q-R1c-1 п. 5) — права ERP вычисляются из разделов ролей,
 * итог провижининга виден в карточке («ERP: выдаётся», «ERP: ошибка»).
 */
export function backendConsequence(t: TFunction, access: RolesAccess): string[] {
  const lines: string[] = [];
  if (access.systemAdmin) lines.push(t("modules:admin.org.consequence.erpAdmin"));
  else if (access.erp) lines.push(t("modules:admin.org.consequence.erpSections"));
  if (access.adminWithoutSystem) lines.push(t("modules:admin.roles.adminNote"));
  return lines;
}
