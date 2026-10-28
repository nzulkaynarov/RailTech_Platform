import type { CatalogItemKind } from "../../../shared/api/generated/model";

/** Типы позиции в порядке показа: товар со склада, под заказ, услуга фикс / по этапам / по времени (SPEC-v3 §7.4). */
export const KINDS: readonly CatalogItemKind[] = [
  "stock",
  "on_order",
  "service_fixed",
  "service_milestones",
  "service_time",
];
