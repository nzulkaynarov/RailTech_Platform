import type { CSSProperties } from "react";

import { type MoneyFormatOptions, type NumberInput } from "../lib/money";
import { useFormat } from "../lib/useFormat";
import "./ui.css";

export interface MoneyTextProps extends Pick<MoneyFormatOptions, "fractionDigits" | "currency"> {
  value: NumberInput;
  /** Жирная итоговая сумма */
  strong?: boolean;
  style?: CSSProperties;
}

/**
 * Сумма: `1 234 567 сум`, неразрывные пробелы, `tabular-nums` (SPEC-v3 §5.3; docs/architecture/platform-frontend.md §5).
 * `currency` — код из ответа как есть: `UZS` и пустой — слово языка («сум», «so‘m»), другая валюта — код (UX-2b).
 */
export function MoneyText({ value, strong, style, ...options }: MoneyTextProps) {
  const format = useFormat();
  return (
    <span className="pf-num" style={strong ? { fontWeight: 600, ...style } : style}>
      {format.money(value, options)}
    </span>
  );
}
