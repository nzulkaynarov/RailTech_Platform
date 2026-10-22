import type { ReactNode } from "react";
import { Link } from "react-router";

import { useFormat } from "../lib/useFormat";
import "./ui.css";

export interface CounterCardProps {
  /** Подпись счётчика: «Входящие без резолюции» */
  label: string;
  value: number | string;
  /** Откуда число: «EDS · Входящие» */
  source?: string;
  /** Раздел, куда ведёт карточка */
  to: string;
}

/**
 * Счётчик Dashboard (03-frontend.md §5): карточка 16/20, подпись 12 px `#6e6e6e`, число 28/600 (строка 36) с
 * `tabular-nums`, подпись источника; вся карточка — ссылка.
 */
export function CounterCard({ label, value, source, to }: CounterCardProps) {
  const format = useFormat();
  return (
    <Link to={to} className="pf-card pf-counter">
      <span className="pf-counter-label">{label}</span>
      <span className="pf-counter-value">
        {typeof value === "number" ? format.number(value) : value}
      </span>
      {source ? <span className="pf-counter-source">{source}</span> : null}
    </Link>
  );
}

/** Сетка счётчиков: четыре колонки на широком окне, меньше — на узком (минимум 168 px на карточку), отступ 16. */
export function CounterGrid({ children }: { children: ReactNode }) {
  return <div className="pf-counters">{children}</div>;
}
