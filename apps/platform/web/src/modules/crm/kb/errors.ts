import type { TFunction } from "i18next";

import { ApiError } from "../../../shared/api/errors";

const NS = "kb:errors.";

/** Коды BFF, у которых есть собственный текст; остальные — общий. */
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

function detail(error: ApiError, key: string): unknown {
  return error.details[key];
}

function fieldsOf(error: ApiError): string[] {
  const fields = detail(error, "fields");
  return Array.isArray(fields) ? fields.filter((f): f is string => typeof f === "string") : [];
}

/** Тексты «что исправить» от CRM на трёх языках (`details.messages`): язык сотрудника, затем русский. */
function formatMessage(error: ApiError, language: string): string | undefined {
  const messages = detail(error, "messages");
  if (!messages || typeof messages !== "object") return undefined;
  const byLanguage = messages as Record<string, unknown>;
  const text = byLanguage[language] ?? byLanguage["ru"];
  return typeof text === "string" && text !== "" ? text : undefined;
}

/**
 * Текст ошибки операции «Базы знаний» для сотрудника. Сначала подкод CRM (`details.reason`: файл больше 25 МБ, не Markdown,
 * нарушен формат), затем поле (`product_key`), затем код BFF, затем общий текст. Нарушение формата показывает «что
 * исправить» на языке сотрудника — текст пишет CRM.
 */
export function kbErrorText(t: TFunction, error: unknown, language: string): string {
  if (!(error instanceof ApiError)) return t(`${NS}DEFAULT`);
  const reason = detail(error, "reason");
  if (typeof reason === "string") {
    if (reason === "kb_format") {
      const message = formatMessage(error, language);
      if (message) return t(`${NS}kb_format`, { message });
    }
    const text = t(`${NS}reasons.${reason}`, { defaultValue: "" });
    if (text) return text;
  }
  if (error.code === "VALIDATION_FAILED") {
    const fields = fieldsOf(error);
    if (fields.includes("product_key")) return t(`${NS}reasons.unknown_product`);
    return t(`${NS}VALIDATION_FAILED`);
  }
  if ((CODES as readonly string[]).includes(error.code)) return t(`${NS}${error.code}`);
  return t(`${NS}DEFAULT`);
}

/** Раздел недоступен роли в CRM (например, справочник продуктов администратору без второй роли). */
export function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403;
}
