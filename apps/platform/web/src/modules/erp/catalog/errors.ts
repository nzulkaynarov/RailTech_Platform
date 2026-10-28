import type { TFunction } from "i18next";

import { ApiError } from "../../../shared/api/errors";

/** Причины (`details.reason`) контракта BFF 0.25.0 с собственным текстом (`catalog:errors.reason.*`). */
const REASONS = new Set([
  "item_name_required",
  "item_kind_invalid",
  "vat_rate_invalid",
  "unit_not_found",
  "category_not_found",
  "offer_price_invalid",
  "offer_currency_invalid",
  "offer_validity_range_invalid",
  "stock_status_not_found",
  "brigade_name_required",
  "brigade_kind_invalid",
  "brigade_headcount_invalid",
  "rate_unit_invalid",
  "crew_rate_invalid",
  "crew_currency_invalid",
  "hs_code_invalid",
  "hs_name_required",
  "hs_validity_range_invalid",
  "hs_code_exists",
  "manufacturer_exists",
  "already_pending",
  "category_request_name_required",
  "file_too_large",
  "file_type_not_allowed",
  "file_content_mismatch",
  "no_file_provided",
  "tech_doc_link_required",
  "tech_doc_kind_invalid",
  "product_not_found",
  "deal_not_found",
  "multipart_required",
  "name_required",
  "already_reviewed",
  "category_required",
  "reason_required",
]);

/**
 * Текст ошибки экрана «Номенклатура и поставщики» по коду контракта: причина (`details.reason`) важнее кода; отказ ERP
 * (`source = erp`) — отдельный текст, потому что право на операцию решает ERP, а не раздел Платформы.
 */
export function catalogErrorText(t: TFunction, error: unknown): string {
  const base = "catalog:errors.";
  if (!(error instanceof ApiError)) return t(`${base}DEFAULT`);
  const reason = error.details["reason"];
  if (typeof reason === "string" && REASONS.has(reason)) return t(`${base}reason.${reason}`);
  if (error.code === "PAYLOAD_TOO_LARGE") return t(`${base}reason.file_too_large`);
  if (error.code === "FORBIDDEN") {
    const backend = error.details["backend_code"];
    if (backend === "SUPPLIER_PRICES_REQUIRED") return t(`${base}SUPPLIER_PRICES_REQUIRED`);
    if (backend === "CREW_RATES_REQUIRED") return t(`${base}CREW_RATES_REQUIRED`);
    return t(error.source === "erp" ? `${base}ERP_FORBIDDEN` : `${base}FORBIDDEN`);
  }
  if (["VALIDATION_FAILED", "CONFLICT", "BACKEND_UNAVAILABLE", "NOT_FOUND"].includes(error.code)) {
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
