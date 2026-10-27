import type { TFunction } from "i18next";

import { entityLabel } from "../../../entities/audit/labels";
import type { AuditEntry } from "../../../shared/api/generated/model";

/** Кто сделал: имя из CRM, иначе из списка сотрудников, иначе роль автора (система, бот) или номер. */
export function actorText(
  t: TFunction,
  entry: AuditEntry,
  names: ReadonlyMap<string, string>,
): string {
  if (entry.actor_name) return entry.actor_name;
  if (entry.actor_id) {
    return names.get(entry.actor_id) ?? t("audit:actorKind.unknown", { id: entry.actor_id });
  }
  return t(`audit:actorKind.${entry.actor_type === "bot" ? "bot" : "system"}`);
}

/** Над чем: «Сотрудник: Анна Демова», «Роль Платформы: Закупки», иначе «Тип №id» или просто «Тип». */
export function entityText(
  t: TFunction,
  entry: AuditEntry,
  names: ReadonlyMap<string, string>,
): string {
  const type = entityLabel(t, entry.entity_type);
  const id = entry.entity_id;
  if (!id) return type;
  const known =
    entry.entity_type === "user"
      ? names.get(id)
      : entry.entity_type === "platform_role"
        ? (entry.after?.["name"] ?? entry.before?.["name"])
        : undefined;
  if (typeof known === "string" && known) {
    return t("audit:entityText.withName", { type, name: known });
  }
  // Числовой номер — «№15»; код вроде `smtp` или `L-2041` — «Тип: код».
  return /^[0-9]+$/.test(id)
    ? t("audit:entityText.withId", { type, id })
    : t("audit:entityText.withName", { type, name: id });
}

/** Куда ведёт объект записи (если у него есть экран в Платформе). */
export function entityHref(entry: AuditEntry): string | null {
  const id = entry.entity_id;
  if (!id) return null;
  if (entry.entity_type === "user")
    return `/admin/org?employee=${encodeURIComponent(id)}&panel=open`;
  if (entry.entity_type === "platform_role") {
    return `/admin/roles?role=${encodeURIComponent(id)}&panel=open&tab=role`;
  }
  return null;
}

/** Начало календарного дня компании (Asia/Tashkent, UTC+5 без перехода на летнее время) со сдвигом в днях. */
export function companyDayStart(date: string, plusDays = 0): string | undefined {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!match) return undefined;
  const moved = new Date(
    Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]) + plusDays),
  );
  return `${moved.toISOString().slice(0, 10)}T00:00:00+05:00`;
}
