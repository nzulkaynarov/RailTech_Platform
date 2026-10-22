import type { Me } from "../../shared/api/generated/model";

/** Роль под аватаром: активная; при нескольких ролях без выбора — «Все роли» (SPEC-v3 §4.1). */
export function roleCaption(me: Me, t: (key: string) => string): string {
  if (me.active_role) return t(`rolesShort.${me.active_role}`);
  const [only] = me.roles;
  return me.roles.length === 1 && only ? t(`rolesShort.${only}`) : t("avatar.rolesMany");
}
