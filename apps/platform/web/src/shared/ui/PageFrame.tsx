import type { ReactNode } from "react";

import "./page-frame.css";

/** Раскладки страницы (docs/architecture/ui-standard.md §9): реестр, объект, настройки/форма. */
export type PageLayout = "registry" | "object" | "settings";

/**
 * Один каркас страницы основного окна: содержимое занимает всю доступную ширину, одинаковые поля слева и справа,
 * `gap` между блоками одинаковый на всех экранах. Читаемость строк обеспечивает раскладка, а не сжатие страницы:
 * `settings` кладёт карточки в сетку 1–3 колонок по ширине самой страницы (container query: до 900 — одна, до 1500 — две,
 * дальше — три); `registry` и `object` — колонка блоков на всю ширину. Карточка, которой нужна вся строка (таблица,
 * журнал), — `PageFrame.Wide`.
 */
export function PageFrame({
  layout,
  children,
  className,
}: {
  layout: PageLayout;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`pf-frame pf-frame--${layout}${className ? ` ${className}` : ""}`}
      data-layout={layout}
    >
      <div className="pf-frame-in">{children}</div>
    </div>
  );
}

/** Блок на всю строку сетки настроек (таблица, журнал, длинная форма). */
PageFrame.Wide = function Wide({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <div className="pf-frame-wide" id={id}>
      {children}
    </div>
  );
};

/** Сетка полей внутри карточки: колонки по ширине карточки, поле не уже ~220 px. */
export function FieldGrid({ children }: { children: ReactNode }) {
  return <div className="pf-field-grid">{children}</div>;
}
