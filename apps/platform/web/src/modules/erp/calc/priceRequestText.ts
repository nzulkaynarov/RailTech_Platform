import type { PriceRequestLine } from "../../../shared/api/generated/model";

/** «Рельс · 20 000 т; Накладка · 5 шт.»: количество с разрядами и единицей строки, а не голое число. */
export function priceRequestLinesText(
  lines: readonly PriceRequestLine[],
  qty: (value: number) => string,
): string {
  return lines.map((l) => `${l.name} · ${qty(l.quantity)}${l.unit ? ` ${l.unit}` : ""}`).join("; ");
}
