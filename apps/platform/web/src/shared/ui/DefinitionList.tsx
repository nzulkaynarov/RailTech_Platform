import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import "./ui.css";

export interface DefinitionItem {
  label: ReactNode;
  /** Пустое значение (`null`, `undefined`, пустая строка) показывается как «—» */
  value?: ReactNode;
}

export interface DefinitionListProps {
  items: readonly DefinitionItem[];
  /** Режим колонок: 1 колонка, 2 колонки или автоматический в зависимости от ширины контейнера */
  columns?: 1 | 2 | "auto";
  className?: string;
}

/**
 * Реквизиты в карточках (docs/architecture/platform-frontend.md §5): подпись 130 px `#595959`, значение справа, отступы 8/16.
 * Адаптирован под режимы ContextPanel (440px и 600px).
 */
export function DefinitionList({ items, columns = "auto", className = "" }: DefinitionListProps) {
  const { t } = useTranslation("ui");

  const columnClass = columns === 2 ? "pf-dl--2col" : columns === 1 ? "pf-dl--1col" : "pf-dl--auto";

  return (
    <div className="pf-dl-wrap">
      <dl className={`pf-dl ${columnClass} ${className}`.trim()}>
        {items.map((item, index) => {
          const empty = item.value === null || item.value === undefined || item.value === "";
          return (
            <div key={index} style={{ display: "contents" }}>
              <dt>{item.label}</dt>
              <dd>
                {empty ? (
                  <>
                    <span aria-hidden="true">—</span>
                    <span className="pf-sr-only">{t("definition.empty")}</span>
                  </>
                ) : (
                  item.value
                )}
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}
