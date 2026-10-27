import type { TFunction } from "i18next";

import { ApiError } from "../../../shared/api/errors";

const NS = "bot:errors.";
const CODES = [
  "FORBIDDEN",
  "NOT_FOUND",
  "BACKEND_UNAVAILABLE",
  "INTEGRATION_FAILED",
  "TOO_MANY_REQUESTS",
  "VALIDATION_FAILED",
  "CONFLICT",
  "SESSION_EXPIRED",
] as const;

/** Текст ошибки операции экрана «Настройки бота» для администратора: подкод CRM, затем код BFF, затем общий текст. */
export function botErrorText(t: TFunction, error: unknown): string {
  if (!(error instanceof ApiError)) return t(`${NS}DEFAULT`);
  const reason = error.details["reason"];
  if (typeof reason === "string") {
    const text = t(`${NS}reasons.${reason}`, { defaultValue: "" });
    if (text) return text;
  }
  if ((CODES as readonly string[]).includes(error.code)) return t(`${NS}${error.code}`);
  return t(`${NS}DEFAULT`);
}

/** Пути невалидных полей из ответа CRM на сохранение раздела («greeting.uz») — для подсветки полей формы. */
export function invalidPaths(error: unknown): string[][] {
  if (!(error instanceof ApiError)) return [];
  const paths = error.details["paths"];
  if (!Array.isArray(paths)) return [];
  return paths
    .filter((p): p is string => typeof p === "string" && p !== "")
    .map((p) => p.split("."));
}
