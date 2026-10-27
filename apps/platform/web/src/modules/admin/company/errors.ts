import type { TFunction } from "i18next";

import { ApiError } from "../../../shared/api/errors";

/** Причины (`details.reason`) контракта BFF 0.8.0, у которых есть свой текст (`company:errors.reason.*`). */
const REASONS = new Set([
  "lookup_in_use",
  "category_has_children",
  "template_in_use",
  "doc_prefix_taken",
  "already_reviewed",
  "invalid_numbering_pattern",
  "file_too_large",
  "multipart_required",
  "unsupported_type",
  "field_not_in_reference",
  "reason_required",
  "category_required",
  "fx_rate_invalid",
  "fx_rate_date_invalid",
  "fx_rate_date_in_future",
  "fx_rate_date_too_old",
]);

/**
 * Текст ошибки Admin · Компания по коду контракта (`COMPANY_NOT_SET`, `VALIDATION_FAILED`, `CONFLICT`, `FORBIDDEN`,
 * `BACKEND_UNAVAILABLE`): причина (`details.reason`) важнее кода; отказ ERP (`source = erp`) — отдельный текст: право на
 * операцию решает ERP, а не раздел Платформы.
 */
export function companyErrorText(t: TFunction, error: unknown): string {
  const base = "company:errors.";
  if (!(error instanceof ApiError)) return t(`${base}DEFAULT`);
  const reason = error.details["reason"];
  if (typeof reason === "string" && REASONS.has(reason)) return t(`${base}reason.${reason}`);
  if (error.code === "FORBIDDEN") {
    if (error.details["restricted"] === "cost_margin") return t(`${base}MARGIN_FORBIDDEN`);
    return t(error.source === "erp" ? `${base}ERP_FORBIDDEN` : `${base}FORBIDDEN`);
  }
  if (
    ["COMPANY_NOT_SET", "VALIDATION_FAILED", "CONFLICT", "BACKEND_UNAVAILABLE"].includes(error.code)
  ) {
    return t(`${base}${error.code}`);
  }
  return t(`${base}DEFAULT`);
}

/** Поля формы, которые ERP назвала в 422 (`details.fields`). */
export function errorFields(error: unknown): string[] {
  if (!(error instanceof ApiError)) return [];
  const fields = error.details["fields"];
  return Array.isArray(fields) ? fields.filter((f): f is string => typeof f === "string") : [];
}

export const isCompanyNotSet = (error: unknown) =>
  error instanceof ApiError && error.code === "COMPANY_NOT_SET";
