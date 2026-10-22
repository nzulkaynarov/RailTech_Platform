import type { Me } from "../../shared/api/generated/model";
import { viewRoleNames } from "../../entities/role/roles";

/** Роль под аватаром: активная; при нескольких ролях без выбора — «Все роли» (SPEC-v3 §4.1). Название — из данных. */
export function roleCaption(me: Me, t: (key: string) => string): string {
  return viewRoleNames(me, t("avatar.rolesMany"));
}
