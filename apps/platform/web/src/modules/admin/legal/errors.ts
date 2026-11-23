import type { TFunction } from "i18next";

import { ApiError } from "../../../shared/api/errors";
import i18n from "../../../shared/i18n";

/** Текст ошибки словами: сначала подкод ERP (`details.reason`), затем код BFF, иначе общий. Сообщение сервера на экран не выводим. */
export function legalErrorText(t: TFunction<"legal">, error: unknown): string {
  if (error instanceof ApiError) {
    const reason = error.details["reason"];
    for (const key of [typeof reason === "string" ? reason : "", error.code]) {
      if (key && i18n.exists(`errors.${key}`, { ns: "legal" })) return t(`errors.${key}`);
    }
  }
  return t("errors.default");
}
