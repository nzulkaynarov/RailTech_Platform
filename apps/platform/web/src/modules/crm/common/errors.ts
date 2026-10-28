import type { TFunction } from "i18next";

import { ApiError } from "../../../shared/api/errors";

/**
 * Текст отказа словами: подкод CRM (`details.reason`), затем код ответа BFF, затем общий текст. `prefix` — ключ словаря
 * с ошибками экрана (`request:errors`).
 */
export function reasonError(t: TFunction, prefix: string, error: unknown): string {
  if (error instanceof ApiError) {
    const reason = error.details["reason"];
    if (typeof reason === "string") {
      const text = t(`${prefix}.${reason}`, { defaultValue: "" });
      if (text) return text;
    }
    const byCode = t(`${prefix}.${error.code}`, { defaultValue: "" });
    if (byCode) return byCode;
  }
  return t(`${prefix}.generic`);
}
