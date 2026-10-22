import type { TFunction } from "i18next";

import type { RoleCode } from "../../app/rbac.generated";
import { erpAccessOfRoles } from "./access";

/**
 * Строка «Что произойдёт» про ERP: роли ERP по карте платформенных ролей (генерируется из platform-rbac.yaml);
 * названия ролей ERP — в i18n, не в контракте. Роль без ролей ERP (только ADMIN) — «администратор».
 */
export function erpConsequence(t: TFunction, roles: readonly RoleCode[]): string | null {
  const { admin, codes } = erpAccessOfRoles(roles);
  if (admin) return t("modules:admin.org.consequence.erpAdmin");
  if (codes.length === 0) return null;
  const names = codes.map((code) =>
    t(`modules:admin.org.erpRoles.${code}`, { defaultValue: code }),
  );
  return t("modules:admin.org.consequence.erpRoles", { roles: names.join(", ") });
}
