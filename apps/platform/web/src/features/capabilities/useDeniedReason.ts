import { useTranslation } from "react-i18next";

import { canEdit, canSee } from "../../app/access";
import { useAuth } from "../../app/auth/useAuth";
import { useGetMyCapabilities } from "../../shared/api/generated/platform-bff";
import { findMissing } from "./model";

/**
 * Почему действие недоступно сотруднику и кто может его разрешить (ПОДПИСЬ-1): `null` — доступно. Раздел закрыт:
 * называется недостающая возможность из каталога ДОСТ-1 и те, кто их выдаёт; каталог не пришёл — общие слова.
 * Права читаются так же, как у самого сервера (`me`), поэтому кнопка и ответ BFF не расходятся.
 */
export function useDeniedReason(resource: string, level: "read" | "full"): string | null {
  const { t } = useTranslation("capabilities");
  const { me } = useAuth();
  const allowed = level === "full" ? canEdit(me, resource) : canSee(me, { resource });
  const mine = useGetMyCapabilities({ query: { enabled: !allowed, retry: false } });
  if (allowed) return null;
  const missing = mine.data ? findMissing(mine.data, [resource], level) : null;
  const names = grantorNames(mine.data?.grantors);
  // Одна обычная фраза: «У вас нет возможности работать с договорами. Её выдают: …»; для возможности без своей фразы — нейтральная.
  const phrase = missing
    ? t(`denied.can.${missing.key}.${missing.needed}`, { defaultValue: "" })
    : "";
  if (phrase === "") {
    return names === ""
      ? t("denied.action")
      : `${t("denied.action")} ${t("denied.actionGrantors", { names })}`;
  }
  const cant = t("denied.cant", { what: phrase });
  return names === "" ? cant : `${cant} ${t("denied.cantGrantors", { names })}`;
}

/** Имена тех, кто выдаёт возможности, через запятую; пусто — имён нет или каталог не пришёл. */
export function grantorNames(grantors: readonly { name: string }[] | undefined): string {
  return (grantors ?? []).map((p) => p.name).join(", ");
}
