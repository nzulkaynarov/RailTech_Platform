import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import "./ui.css";

export interface DefinitionItem {
  label: ReactNode;
  /** Пустое значение (`null`, `undefined`, пустая строка) показывается как «—» */
  value?: ReactNode;
}

/**
 * Реквизиты в карточках (03-frontend.md §5): подпись 130 px `#595959`, значение справа, отступы 8/16. Родной `dl`
 * (термин → определение) вместо `ProDescriptions`: запросов и типов значений здесь нет, а разметка для скринридера
 * точнее. Пустое значение — «—» и слово «не указано» для скринридера.
 */
export function DefinitionList({ items }: { items: readonly DefinitionItem[] }) {
  const { t } = useTranslation("ui");
  return (
    <dl className="pf-dl">
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
  );
}
