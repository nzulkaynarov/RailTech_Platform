import type { TFunction } from "i18next";

import { ApiError } from "../../../shared/api/errors";

/** Текст ошибки справочника: причина EDS (`details.reason`) важнее кода. */
export function dictionaryErrorText(t: TFunction<"letters">, error: unknown): string {
  const base = "settings.dict.errors.";
  if (!(error instanceof ApiError)) return t(`${base}DEFAULT`);
  const reason = error.details["reason"];
  if (reason === "name_taken" || reason === "value_in_use" || reason === "dictionary_closed") {
    return t(`${base}${reason}`);
  }
  return t(error.code === "FORBIDDEN" ? `${base}FORBIDDEN` : `${base}DEFAULT`);
}
