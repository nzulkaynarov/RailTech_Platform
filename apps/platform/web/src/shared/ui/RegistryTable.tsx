import type { RowData } from "@tanstack/react-table";
import { Card, Pagination } from "antd";
import type { ReactNode } from "react";

import { DataBlock, ListSkeleton } from "./DataBlock";
import { DataTable, type DataTableProps } from "./DataTable/DataTable";

import "./registry-table.css";

/** Постраничный вывод с сервера: один переключатель страниц на все списки (ЕВ-1а). */
export interface RegistryPagination {
  current: number;
  pageSize: number;
  total: number;
  onChange: (page: number) => void;
  /** Подпись переключателя для экранного чтеца */
  label: string;
  /** Слева в подвале: «Записей: 120» (живой регион) */
  summary?: ReactNode;
}

export interface RegistryTableProps<Row extends RowData> extends Omit<
  DataTableProps<Row>,
  "className"
> {
  /** Первая загрузка: скелет в форме таблицы вместо вращающегося значка */
  loading?: boolean;
  /** Сколько строк рисовать в скелете (размер страницы) */
  skeletonRows?: number;
  /** Ошибка загрузки: готовое `EmptyState` с кнопкой «Повторить» */
  error?: ReactNode;
  /** Пусто: готовое `EmptyState` (статус словами, что здесь будет, одно действие) */
  empty: ReactNode;
  /** Идёт загрузка с новыми условиями при прежних строках: полоса сверху, высота не меняется */
  busy?: boolean;
  /** Ключ показанных данных (`useShownKey`) */
  resetKey?: string;
  /** Выбранная строка (открыта в боковом окне): общая заливка и `data-selected` */
  selectedKey?: string | null;
  /** Строка фильтров внутри рамки, над таблицей */
  toolbar?: ReactNode;
  /** Вместо таблицы на узком блоке или телефоне: список строк */
  list?: ReactNode;
  pagination?: RegistryPagination;
  /** Список уже лежит внутри карточки страницы (вкладка настроек): своей рамки не рисуем, вид таблицы тот же */
  nested?: boolean;
}

/**
 * Рамка рабочего списка (ЕВ-1а, отчёт 2026-11-22 §7): белая карточка с рамкой, шапка таблицы с подложкой и заголовками
 * влево, линии между строками, общая заливка выбранной строки, скелет первой загрузки, пустое состояние и один
 * переключатель страниц. Вид таблицы даёт `DataTable` (`data-table.css`), поэтому экран не задаёт ни `className`, ни свой
 * CSS таблицы: новый экран нельзя собрать иначе (запрет — `ui-guards`). Состояния взаимоисключающие: загрузка, ошибка,
 * пусто, список.
 */
export function RegistryTable<Row extends RowData>({
  loading = false,
  skeletonRows,
  error,
  empty,
  busy = false,
  resetKey,
  selectedKey = null,
  toolbar,
  list,
  pagination,
  nested = false,
  rowAttrs,
  rows,
  rowKey,
  pageSize,
  ...table
}: RegistryTableProps<Row>) {
  let body: ReactNode;
  if (loading) {
    body = <ListSkeleton rows={skeletonRows ?? pageSize ?? pagination?.pageSize ?? 8} />;
  } else if (error !== undefined && error !== null) {
    body = error;
  } else if (rows.length === 0) {
    body = empty;
  } else if (list !== undefined) {
    body = list;
  } else {
    body = (
      <DataTable<Row>
        {...table}
        rows={rows}
        rowKey={rowKey}
        pageSize={pageSize}
        rowAttrs={(row) => ({
          ...rowAttrs?.(row),
          ...(selectedKey !== null && rowKey(row) === selectedKey
            ? { "data-selected": "true" }
            : {}),
        })}
      />
    );
  }
  const showPager = pagination !== undefined && !loading && rows.length > 0;
  return (
    <Card className={nested ? "pf-reg pf-reg--nested" : "pf-reg"} styles={{ body: { padding: 0 } }}>
      {toolbar}
      <DataBlock busy={busy} resetKey={resetKey}>
        {body}
      </DataBlock>
      {showPager ? (
        <div className="pf-reg-footer">
          <span className="pf-hint" aria-live="polite">
            {pagination.summary}
          </span>
          {pagination.total > pagination.pageSize ? (
            <Pagination
              current={pagination.current}
              pageSize={pagination.pageSize}
              total={pagination.total}
              showSizeChanger={false}
              size="small"
              aria-label={pagination.label}
              onChange={pagination.onChange}
            />
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}
