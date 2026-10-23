import { type ReactNode, useId } from "react";

import { DocNumber } from "./DocNumber";
import "./ui.css";

export interface DocRowProps {
  /** Номер документа (`СЧ-2026/142`) */
  number: string;
  /** Вид документа под номером: «Счёт на предоплату 50 %» */
  type: ReactNode;
  /** Тег статуса (`StatusTag`) */
  status: ReactNode;
  /** История словами рядом с тегом: «выставлен 27.10 · клиент нажал «Я оплатил» 28.10» */
  note?: ReactNode;
  /** Одно действие строки (кнопка или ссылка) */
  action?: ReactNode;
  /** Базовый адрес для ссылки на номер */
  base?: string;
}

/**
 * Строка «Документы проекта» (docs/architecture/platform-frontend.md §5): сетка `150px 1fr auto`, отступ 14/24 — тип и номер · тег статуса и
 * история · действие. На узкой ширине колонки идут друг под другом. Рендерит `li`: использовать только внутри
 * `DocList` (или своего `ul`).
 */
export function DocRow({ number, type, status, note, action, base }: DocRowProps) {
  return (
    <li className="pf-doc">
      <div>
        <div className="pf-doc-number">
          <DocNumber number={number} base={base} />
        </div>
        <div className="pf-hint">{type}</div>
      </div>
      <div>
        {status}
        {note ? (
          <>
            {" "}
            <span className="pf-hint">{note}</span>
          </>
        ) : null}
      </div>
      <div className="pf-doc-action">{action}</div>
    </li>
  );
}

/** Карточка со списком документов: заголовок 14/600, действие справа («+ Добавить документ»), строки `DocRow`. */
export function DocList({
  title,
  extra,
  headingLevel = 2,
  children,
}: {
  title: string;
  extra?: ReactNode;
  headingLevel?: 2 | 3;
  children: ReactNode;
}) {
  const headingId = useId();
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <section className="pf-card pf-docs" aria-labelledby={headingId}>
      <div className="pf-card-head">
        <Heading id={headingId} className="pf-card-title">
          {title}
        </Heading>
        {extra}
      </div>
      <ul className="pf-list">{children}</ul>
    </section>
  );
}
