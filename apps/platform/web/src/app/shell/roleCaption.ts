import type { Me } from "../../shared/api/generated/model";

/** Роль под аватаром: активная; при нескольких ролях без выбора — «Все роли» (SPEC-v3 §4.1). */
// TODO(ADR-0012): краткое название роли приходит из данных `/me` (поле роли), а не из `rolesShort.<код>` в i18n.
export function roleCaption(me: Me, t: (key: string) => string): string {
  if (me.active_role) return t(`rolesShort.${me.active_role}`);
  const [only] = me.roles;
  return me.roles.length === 1 && only ? t(`rolesShort.${only}`) : t("avatar.rolesMany");
}
