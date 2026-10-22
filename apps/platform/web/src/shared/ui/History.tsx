import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { CheckIcon } from "./icons";
import "./ui.css";

export type HistoryState = "done" | "waiting" | "todo";

export interface HistoryItem {
  state: HistoryState;
  /** Что произошло или чего ждём */
  title: ReactNode;
  /** Дата · кто: «25.10 · Рустамов А.К.» */
  meta?: ReactNode;
}

/**
 * Журнал документа (03-frontend.md §5): точка 16 px — сделано (зелёная заливка и галочка), ждёт (рамка `#1668dc` на
 * `#e6f4ff` и точка внутри), не начато (рамка `#d9d9d9`); вертикальная линия 2 px `#f0f0f0`. Состояние — не только
 * цветом: форма точки и слово для скринридера.
 */
export function History({ items, label }: { items: readonly HistoryItem[]; label?: string }) {
  const { t } = useTranslation("ui");
  return (
    <ol className="pf-history" aria-label={label}>
      {items.map((item, index) => (
        <li key={index} className="pf-history-item">
          <span className={`pf-history-dot pf-history-dot--${item.state}`} aria-hidden="true">
            {item.state === "done" ? <CheckIcon size={10} /> : null}
          </span>
          <div>
            <div className="pf-history-title">
              <span className="pf-sr-only">{t(`history.${item.state}`)}: </span>
              {item.title}
            </div>
            {item.meta ? <div className="pf-hint">{item.meta}</div> : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
