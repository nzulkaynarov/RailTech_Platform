import type { TFunction } from "i18next";

import { ApiError } from "../../../shared/api/errors";

/** Причина отказа действия по проекту словом: подкод ERP (`details.reason`), иначе по статусу ответа. */
export function reasonText(t: TFunction<"projects">, error: unknown): string {
  if (error instanceof ApiError) {
    const reason = error.details["reason"];
    if (typeof reason === "string" && t(`errors.${reason}`, { defaultValue: "" }) !== "") {
      return t(`errors.${reason}`);
    }
    if (error.status === 413) return t("errors.payload");
    if (error.status === 403) return t("errors.forbidden");
    if (error.status === 409) return t("errors.contract_transition_not_allowed");
    if (error.status >= 500 || error.status === 0) return t("errors.unavailable");
    return t("errors.unknown");
  }
  return error instanceof TypeError ? t("errors.unavailable") : t("errors.unknown");
}

/** Отказ из-за того, что документ уже в другом статусе (кто-то опередил): карточку надо обновить. */
export function isStale(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}
