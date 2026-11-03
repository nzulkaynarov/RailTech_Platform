import type { CatalogItemKind, CatalogOfferSource } from "../../../shared/api/generated/model";

/** Типы позиции в порядке показа: товар со склада, под заказ, услуга фикс / по этапам / по времени (SPEC-v3 §7.4). */
export const KINDS: readonly CatalogItemKind[] = [
  "stock",
  "on_order",
  "service_fixed",
  "service_milestones",
  "service_time",
];

/** Источник цены поставщика (CAT-1): прайс, ответ на запрос цены, вручную. */
export const OFFER_SOURCES: readonly CatalogOfferSource[] = ["price_list", "rfq_reply", "manual"];
