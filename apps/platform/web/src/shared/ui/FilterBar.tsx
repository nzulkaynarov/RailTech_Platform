import type { CSSProperties, ReactNode } from "react";

import { ToolsSlot } from "./DataTable/RegistryTools";

import "./ui.css";

/**
 * Строка фильтров реестра (стандарт интерфейса §7 и §9, UI-8): вкладки статусов, поиск, выборы — в одну строку с переносом,
 * «Столбцы» таблицы — у правого края (`tools`). Один компонент во всех модулях вместо своих классов. Подписи полей
 * (`FilterField`) — для экранного чтеца: само поле показывает значение («Любой статус») или подсказку.
 */
export function FilterBar({
  label,
  tools = false,
  inset = false,
  actions,
  children,
}: {
  /** Имя группы для экранного чтеца, например «Фильтры проектов» */
  label?: string;
  /** Поставить сюда «Столбцы» таблицы экрана (`ToolsSlot`) */
  tools?: boolean;
  /** Строка внутри карточки над таблицей: поля карточки и черта снизу */
  inset?: boolean;
  /** Действие вкладки у правого края, после «Столбцов» («Новый заказ»), когда шапки страницы у вкладки нет */
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      className={inset ? "pf-filter-bar pf-filter-bar--inset" : "pf-filter-bar"}
      role="search"
      aria-label={label}
    >
      {children}
      {tools ? <ToolsSlot /> : null}
      {actions ? <div className="pf-filter-actions">{actions}</div> : null}
    </div>
  );
}

/**
 * Поле строки фильтров: подпись для экранного чтеца и элемент. `grow` — поле тянется (поиск); `width` — ширина выбора,
 * px (по умолчанию 200; на телефоне — во всю ширину). Вкладки и флажки кладутся в `FilterBar` без обёртки.
 */
export function FilterField({
  id,
  label,
  grow = false,
  width,
  visibleLabel = false,
  children,
}: {
  id: string;
  label: ReactNode;
  grow?: boolean;
  width?: number;
  /** Короткая подпись слева от поля («С», «По») — когда значение поля само не говорит, что это за поле */
  visibleLabel?: boolean;
  children: ReactNode;
}) {
  const classes = [
    "pf-filter-field",
    grow ? "pf-filter-field--grow" : "",
    visibleLabel ? "pf-filter-field--labeled" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div
      className={classes}
      style={
        grow || width === undefined
          ? undefined
          : ({ "--pf-filter-width": `${String(width)}px` } as CSSProperties)
      }
    >
      <label htmlFor={id} className={visibleLabel ? "pf-filter-label" : "pf-sr-only"}>
        {label}
      </label>
      {children}
    </div>
  );
}
