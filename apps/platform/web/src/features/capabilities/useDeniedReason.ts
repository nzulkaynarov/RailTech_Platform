import { useTranslation } from "react-i18next";

import { canEdit, canSee } from "../../app/access";
import { useAuth } from "../../app/auth/useAuth";
import { useGetMyCapabilities } from "../../shared/api/generated/platform-bff";
import { findMissing, pickText } from "./model";

/**
 * Почему действие недоступно сотруднику и кто может его разрешить (ПОДПИСЬ-1): `null` — доступно. Раздел закрыт:
 * называется недостающая возможность из каталога ДОСТ-1 и те, кто их выдаёт; каталог не пришёл — общие слова.
 * Права читаются так же, как у самого сервера (`me`), поэтому кнопка и ответ BFF не расходятся.
 */
export function useDeniedReason(resource: string, level: "read" | "full"): string | null {
  const { t, i18n } = useTranslation("capabilities");
  const { me } = useAuth();
  const allowed = level === "full" ? canEdit(me, resource) : canSee(me, { resource });
  const mine = useGetMyCapabilities({ query: { enabled: !allowed, retry: false } });
  if (allowed) return null;
  const missing = mine.data ? findMissing(mine.data, [resource], level) : null;
  const grantors = mine.data?.grantors;
  const who =
    grantors === undefined
      ? t("denied.who")
      : grantors.length === 0
        ? t("denied.nobody")
        : t("denied.grantors", { names: grantors.map((p) => p.name).join(", ") });
  if (!missing) return `${t("denied.action")} ${who}`;
  const name = pickText(missing.name, i18n.language);
  return `${t("denied.actionNeed", { name, level: t(`levelVerb.${missing.needed}`) })} ${who}`;
}
