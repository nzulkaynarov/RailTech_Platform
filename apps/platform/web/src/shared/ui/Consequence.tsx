import { type ReactNode, useId } from "react";
import { useTranslation } from "react-i18next";

import "./ui.css";

export interface ConsequenceProps {
  /** 3–4 строки «что произойдёт» из словаря действий (`dictionary.actions.*`, SPEC-v3 приложение Б) */
  items: readonly ReactNode[];
  /** Заголовок блока; по умолчанию «Что произойдёт» */
  title?: string;
}

/**
 * Блок «Что произойдёт» под главной кнопкой (SPEC-v3 §5.3): фон `#fafafa`, рамка `#f0f0f0`, радиус 8, отступ 12, текст
 * 13 px; каждая строка — шаг с номером. Группа с именем, а не заголовок страницы: блок стоит внутри бокового окна.
 */
export function Consequence({ items, title }: ConsequenceProps) {
  const { t } = useTranslation("ui");
  const titleId = useId();
  return (
    <div className="pf-consequence" role="group" aria-labelledby={titleId}>
      <p id={titleId} className="pf-consequence-title">
        {title ?? t("consequence.title")}
      </p>
      <ol className="pf-consequence-list">
        {items.map((item, index) => (
          <li key={index} className="pf-consequence-item">
            <span className="pf-consequence-step" aria-hidden="true">
              {index + 1}
            </span>
            <span>{item}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
