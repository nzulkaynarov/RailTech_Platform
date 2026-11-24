import { Alert, Button, Pagination } from "antd";
import { Dialog } from "../../../shared/ui/Dialog";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useViewport } from "../../../app/shell/useViewport";
import type { CatalogOffer } from "../../../shared/api/generated/model";
import { DataTable, type DataColumn } from "../../../shared/ui/DataTable/DataTable";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { FormSheet } from "../../../shared/ui/FormSheet";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { catalogErrorText } from "./errors";

import "./catalog.css";

export const PAGE_SIZE = 25;

export interface Column<T> {
  key: string;
  title: string;
  render: (row: T) => ReactNode;
  /** Число: выравнивание по правому краю */
  num?: boolean;
  /** Ширина колонки, px; без неё — числа 130 px, остальные делят остаток поровну (UX-1c, S9) */
  width?: number;
  /** Колонка сортируется щелчком по шапке: ключ отправляется серверу (`sort`), порядок — в адресе страницы (Х-15) */
  sortKey?: string;
  /** Приоритет при нехватке ширины (`DataColumn.priority`): больше — колонка прячется раньше */
  priority?: number;
  /** Одна строка с многоточием, полный текст — в подсказке */
  truncate?: boolean;
}

/** Ширина колонки таблицы: своя, у чисел 130 px, у прочих — гибкая (`null`). */
function columnWidth<T>(column: Column<T>): number | null {
  return column.width ?? (column.num ? 130 : null);
}

/**
 * Список строк: таблица на широком экране (прокручиваемая область доступна с клавиатуры) и карточки на телефоне. Первая
 * колонка — «главная»: в ней находится кнопка открытия строки (название), у карточки это её заголовок.
 */
export function DataList<T extends object>({
  tableId,
  label,
  rows,
  columns,
  rowKey,
  selectedKey,
  sortMode,
}: {
  /** Идентификатор таблицы для настроек столбцов сотрудника, например `erp.catalog.items` */
  tableId: string;
  label: string;
  rows: readonly T[];
  columns: readonly Column<T>[];
  rowKey: (row: T) => string;
  selectedKey?: string | null;
  /** `server` — постраничный список, порядок отдаёт сервер (колонки с `sortKey`) */
  sortMode?: "client" | "server";
}) {
  const { mobile } = useViewport();
  const [primary, ...rest] = columns;
  if (!primary) return null;
  if (mobile) {
    return (
      <ul className="pf-cat-cards" aria-label={label}>
        {rows.map((row) => (
          <li key={rowKey(row)} className="pf-cat-card" data-selected={selectedKey === rowKey(row)}>
            <div>{primary.render(row)}</div>
            <dl>
              {rest.map((column) => (
                <div key={column.key} style={{ display: "contents" }}>
                  <dt>{column.title}</dt>
                  <dd>{column.render(row)}</dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <DataTable<T>
      tableId={tableId}
      caption={label}
      scrollLabel={label}
      className="pf-cat-table"
      flexMin={160}
      rows={rows}
      rowKey={rowKey}
      {...(sortMode ? { sortMode } : {})}
      rowAttrs={(row) => ({ "data-selected": selectedKey === rowKey(row) })}
      columns={columns.map((column, index) => ({
        id: column.key,
        header: column.title,
        ...(column.sortKey ? { sortKey: column.sortKey } : {}),
        width: columnWidth(column),
        numeric: column.num,
        ...(column.priority ? { priority: column.priority } : {}),
        ...(column.truncate ? { truncate: true } : {}),
        cellClassName: index === 0 ? "pf-cat-main" : undefined,
        cell: column.render,
      }))}
    />
  );
}

/**
 * Таблица внутри карточки или окна (предложения, история цены, отчёт загрузки прайса) — общая `DataTable` без «Столбцов»
 * (стандарт §7): ширины по типу, числа справа, прокрутка в своей области.
 */
export function PanelTable<T extends object>({
  tableId,
  label,
  rows,
  columns,
  rowKey,
}: {
  tableId: string;
  label: string;
  rows: readonly T[];
  columns: readonly DataColumn<T>[];
  rowKey: (row: T) => string;
}) {
  return (
    <DataTable<T>
      tableId={tableId}
      caption={label}
      scrollLabel={label}
      className="pf-cat-offers"
      flexMin={140}
      rows={rows}
      rowKey={rowKey}
      columns={columns}
      toolsTarget={null}
    />
  );
}

/** Страницы списка; показывается, только когда строк больше одной страницы. */
export function Pager({
  total,
  page,
  pageSize = PAGE_SIZE,
  onChange,
}: {
  total: number;
  page: number;
  pageSize?: number;
  onChange: (page: number) => void;
}) {
  if (total <= pageSize) return null;
  return (
    <div className="pf-cat-pager">
      <Pagination
        current={page}
        total={total}
        pageSize={pageSize}
        showSizeChanger={false}
        onChange={onChange}
      />
    </div>
  );
}

/** Окно с формой: «Что произойдёт» под полями, ошибка словами, закрытие сбрасывает форму. */
export function FormModal({
  title,
  okLabel,
  loading,
  error,
  disabled = false,
  onOk,
  onCancel,
  children,
}: {
  title: string;
  okLabel: string;
  loading: boolean;
  error?: unknown;
  disabled?: boolean;
  onOk: () => void;
  onCancel: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation("catalog");
  return (
    <Dialog
      open
      title={title}
      onCancel={onCancel}
      footer={[
        <Button key="cancel" onClick={onCancel}>
          {t("cancel")}
        </Button>,
        <Button key="ok" type="primary" loading={loading} disabled={disabled} onClick={onOk}>
          {okLabel}
        </Button>,
      ]}
    >
      <div className="pf-cat-form">
        {children}
        {error ? (
          <Alert type="error" showIcon role="alert" message={catalogErrorText(t, error)} />
        ) : null}
      </div>
    </Dialog>
  );
}

/**
 * Форма на 4 и больше полей — выезжающей панелью 480 px (стандарт интерфейса §6, общий `FormSheet` в режиме `drawer`:
 * карточки каталога сами открыты выезжающим окном, форма встаёт поверх): подвал с «Отмена» и главной кнопкой закреплён,
 * ошибка словами — над полями. Те же свойства, что у `FormModal`: замена обёртки без правки формы.
 */
export function FormPanel({
  title,
  okLabel,
  loading,
  error,
  disabled = false,
  dirty,
  onOk,
  onCancel,
  children,
}: {
  title: string;
  okLabel: string;
  loading: boolean;
  error?: unknown;
  disabled?: boolean;
  dirty?: boolean;
  onOk: () => void;
  onCancel: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation("catalog");
  return (
    <FormSheet
      title={title}
      submitLabel={okLabel}
      saving={loading}
      submitDisabled={disabled}
      layer="drawer"
      {...(dirty === undefined ? {} : { dirty })}
      onSubmit={onOk}
      onCancel={onCancel}
      error={
        error ? (
          <Alert type="error" showIcon role="alert" message={catalogErrorText(t, error)} />
        ) : undefined
      }
    >
      <div className="pf-cat-form">{children}</div>
    </FormSheet>
  );
}

/** Срок действия цены словом и цветом: действует, истекает в ближайшие 14 дней, истёк. */
export function ValidityTag({ validity }: { validity: CatalogOffer["validity"] }) {
  const { t } = useTranslation("catalog");
  return (
    <StatusTag kind="validity" status={validity}>
      {t(`validity.${validity}`)}
    </StatusTag>
  );
}

/** Цена закупки или слово «скрыта» (нет поля `supplier_prices`). */
export function PriceCell({ price }: { price: CatalogOffer["price"] }) {
  const { t } = useTranslation("catalog");
  if (price === null) {
    return <span className="pf-hint">{t("offers.priceHidden")}</span>;
  }
  return <MoneyText value={price.amount} currency={price.currency} />;
}
