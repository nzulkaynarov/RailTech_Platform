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
 * Счётчик Dashboard (docs/architecture/platform-frontend.md §5): карточка 16/20, подпись 12 px `#6e6e6e`, число 28/600 (строка 36) с
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

/**
 * Счётчики до ответа (UX-1c, аудит 2026-10-30, S10): карточки той же высоты (подпись, число, источник), чтобы очередь под
 * ними не съезжала, когда придут числа. `count` — сколько карточек было в прошлый раз.
 */
export function CounterGridSkeleton({ count }: { count: number }) {
  return (
    <div className="pf-counters" aria-hidden="true" data-pf-skeleton="">
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="pf-card pf-counter pf-counter-skel">
          <span className="pf-counter-label">
            <span className="pf-counter-skel-bar" style={{ width: "70%" }} />
          </span>
          <span className="pf-counter-value">
            <span className="pf-counter-skel-bar" style={{ width: 40 }} />
          </span>
          <span className="pf-counter-source">
            <span className="pf-counter-skel-bar" style={{ width: "55%" }} />
          </span>
        </div>
      ))}
    </div>
  );
}
