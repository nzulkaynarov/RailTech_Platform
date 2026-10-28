import type { TFunction } from "i18next";

import { ApiError } from "../../../shared/api/errors";
import i18n from "../../../shared/i18n";

/** Текст ошибки словами: сначала подкод CRM, затем код BFF, иначе общий. Сообщение сервера на экран не выводим. */
export function articleErrorText(t: TFunction<"articles">, error: unknown): string {
  if (error instanceof ApiError) {
    const reason = error.details["reason"];
    for (const key of [typeof reason === "string" ? reason : "", error.code]) {
      if (key && i18n.exists(`editor.errors.${key}`, { ns: "articles" })) {
        return t(`editor.errors.${key}`);
      }
    }
  }
  return t("editor.errors.default");
}
