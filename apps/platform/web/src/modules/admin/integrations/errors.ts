import type { TFunction } from "i18next";

import { ApiError } from "../../../shared/api/errors";

const NS = "integrations:errors.";

/** Коды BFF (0.7.0), у которых есть собственный текст; остальные — по `reason` подкода CRM или общий. */
const CODES = [
  "WRONG_PASSWORD",
  "ACCOUNT_LOCKED",
  "NOT_CONFIGURED",
  "SECRETS_KEY_MISSING",
  "SERVICE_NOT_SWITCHABLE",
  "INTEGRATION_FAILED",
  "FORBIDDEN",
  "BACKEND_UNAVAILABLE",
  "TOO_MANY_REQUESTS",
  "VALIDATION_FAILED",
  "CONFLICT",
  "SESSION_EXPIRED",
] as const;

/** Текст по подкоду CRM (`erp_unavailable`, `smtp_auth_failed`, …); неизвестный подкод — пустая строка. */
export function reasonText(t: TFunction, reason: string): string {
  return t(`${NS}reasons.${reason}`, { defaultValue: "" });
}

export function errorReason(error: unknown): string | undefined {
  if (!(error instanceof ApiError)) return undefined;
  const reason = error.details["reason"];
  return typeof reason === "string" ? reason : undefined;
}

/**
 * Текст ошибки операции экрана «Внешние интеграции» для администратора. Сначала — подкод CRM (`details.reason`: почему
 * не прошла проверка связи, какое поле не принято), затем код BFF, затем общий текст. Значений секретов в ошибке нет.
 */
export function integrationErrorText(t: TFunction, error: unknown): string {
  if (!(error instanceof ApiError)) return t(`${NS}DEFAULT`);
  const reason = errorReason(error);
  if (reason && error.code !== "WRONG_PASSWORD") {
    const text = reasonText(t, reason);
    if (text) return text;
  }
  if ((CODES as readonly string[]).includes(error.code)) return t(`${NS}${error.code}`);
  return t(`${NS}DEFAULT`);
}

export function isWrongPassword(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.code === "WRONG_PASSWORD" || error.code === "ACCOUNT_LOCKED")
  );
}

/** Раздел недоступен роли в CRM (например, директору — модели и бэкапы): не поломка, а пустое состояние. */
export function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403;
}
