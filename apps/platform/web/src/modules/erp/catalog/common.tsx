import { Alert, Button, Modal, Pagination } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useViewport } from "../../../app/shell/useViewport";
import type { CatalogOffer } from "../../../shared/api/generated/model";
import { Consequence } from "../../../shared/ui/Consequence";
import { TableCols } from "../../../shared/ui/DataBlock";
import { tableMinWidth } from "../../../shared/ui/tableWidth";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { ScrollRegion } from "../../../shared/ui/FormParts";
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
  label,
  rows,
  columns,
  rowKey,
  selectedKey,
}: {
  label: string;
  rows: readonly T[];
  columns: readonly Column<T>[];
  rowKey: (row: T) => string;
  selectedKey?: string | null;
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
  const widths = columns.map(columnWidth);
  return (
    <ScrollRegion label={label}>
      <table
        className="pf-cat-table pf-fixed-table"
        style={{ minWidth: tableMinWidth(widths, 160) }}
      >
        <caption className="pf-sr-only">{label}</caption>
        <TableCols widths={widths} />
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col" className={column.num ? "pf-col-num" : undefined}>
                {column.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} data-selected={selectedKey === rowKey(row)}>
              {columns.map((column, index) => (
                <td
                  key={column.key}
                  className={[column.num ? "pf-col-num" : "", index === 0 ? "pf-cat-main" : ""]
                    .filter(Boolean)
                    .join(" ")}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
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
  items,
  loading,
  error,
  disabled = false,
  onOk,
  onCancel,
  children,
}: {
  title: string;
  okLabel: string;
  items: readonly ReactNode[];
  loading: boolean;
  error?: unknown;
  disabled?: boolean;
  onOk: () => void;
  onCancel: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation("catalog");
  return (
    <Modal
      open
      title={title}
      onCancel={onCancel}
      destroyOnHidden
      maskClosable={false}
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
        <Consequence items={items} />
      </div>
    </Modal>
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
