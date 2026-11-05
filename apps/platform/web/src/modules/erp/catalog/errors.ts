import type { TFunction } from "i18next";

import { ApiError } from "../../../shared/api/errors";

/** Причины (`details.reason`) контракта BFF 0.26.0 с собственным текстом (`catalog:errors.reason.*`). */
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
  // CAT-1: поставщики, цены поставщиков, загрузка прайса, изменения карточек, публикация
  "supplier_exists",
  "offer_exists",
  "proposal_decided",
  "proposal_stale",
  "product_incomplete",
  "supplier_id_required",
  "tin_invalid",
  "supplier_name_required",
  "country_not_found",
  "currency_not_found",
  "brand_not_found",
  "item_hs_code_invalid",
  "delivery_basis_not_found",
  "supplier_not_found",
  "supplier_invalid",
  "valid_date_invalid",
  "rows_token_invalid",
  "offer_source_invalid",
  "role_not_permitted",
  // PART-1: доступ партнёра в кабинет
  "contact_exists",
  "contact_email_ambiguous",
  "email_delivery_failed",
  "module_not_allowed",
  "contact_name_required",
  "contact_email_required",
  // CAT-CARD-1: фото, документы товара, гарантия
  "image_limit_reached",
  "image_main_required",
  "image_order_invalid",
  "warranty_months_invalid",
  "tech_doc_date_invalid",
  "tech_doc_validity_range_invalid",
  // PART-3: очередь проверки партнёров
  "product_not_on_review",
  "review_reason_required",
  "review_issues_invalid",
  "review_reason_too_long",
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
