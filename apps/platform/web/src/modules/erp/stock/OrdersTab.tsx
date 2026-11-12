import { Button, Card, Checkbox, Input, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { useViewport } from "../../../app/shell/useViewport";
import type { SupplierOrderRow, SupplierOrderStatus } from "../../../shared/api/generated/model";
import { useListSupplierOrders } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DataTable, type DataColumn } from "../../../shared/ui/DataTable/DataTable";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { ORDER_STATUSES, useStateLabels } from "./api";
import { OrderCreateModal } from "./OrderCreateModal";
import { MoneyText } from "../../../shared/ui/MoneyText";

/** Ширины колонок: номер, поставщик (гибкая), заявки, ожидается, статус, приёмка, [сумма], действие (UX-1c, S9) */
export function OrderStatusTag({ status }: { status: SupplierOrderStatus }) {
  const { t } = useTranslation("stock");
  return (
    <StatusTag kind="supplierOrder" status={status}>
      {t(`orders.status.${status}`)}
    </StatusTag>
  );
}

function Expected({ row }: { row: SupplierOrderRow }) {
  const { t } = useTranslation("stock");
  const { date } = useFormat();
  if (!row.expected_date) return <span className="pf-hint">—</span>;
  return (
    <span className="pf-calc-due">
      <span className="pf-num">{date(row.expected_date)}</span>
      {row.overdue && row.days_overdue ? (
        <StatusTag tone="red">{t("orders.overdueDays", { count: row.days_overdue })}</StatusTag>
      ) : null}
    </span>
  );
}

function Receipt({ row }: { row: SupplierOrderRow }) {
  const { t } = useTranslation("stock");
  if (row.status === "draft" || row.status === "cancelled")
    return <span className="pf-hint">—</span>;
  return (
    <span>
      <span className="pf-num">
        {t("orders.receivedOf", { received: row.received_quantity, total: row.quantity })}
      </span>
      {row.receipt_state === "partial" ? (
        <span className="pf-hint"> · {t("orders.receipt.partial")}</span>
      ) : null}
    </span>
  );
}

function Requests({ row }: { row: SupplierOrderRow }) {
  if (row.requests.length === 0) return <span className="pf-hint">—</span>;
  return (
    <span>
      {row.requests.map((r, index) => (
        <span key={r.number}>
          {index > 0 ? ", " : ""}
          <Link className="pf-focusable" to={r.path}>
            {r.number}
          </Link>
        </span>
      ))}
    </span>
  );
}

function Rows({ items, prices }: { items: readonly SupplierOrderRow[]; prices: boolean }) {
  const { t } = useTranslation("stock");
  const { mobile } = useViewport();
  if (mobile) {
    return (
      <ul className="pf-calc-cards" aria-label={t("orders.caption")}>
        {items.map((row) => (
          <li key={row.number}>
            <div className="pf-calc-card-head">
              <Link className="pf-focusable pf-calc-number" to={row.path}>
                {row.number}
              </Link>
              <OrderStatusTag status={row.status} />
            </div>
            <p className="pf-calc-card-title">{row.supplier.name}</p>
            <p className="pf-hint">
              <Expected row={row} />
            </p>
            <div className="pf-calc-card-foot">
              <Receipt row={row} />
              <LinkButton
                size="small"
                to={row.path}
                aria-label={t("orders.openLabel", { number: row.number })}
              >
                {t("orders.open")}
              </LinkButton>
            </div>
          </li>
        ))}
      </ul>
    );
  }
  // Ширины по типу (T1); сумма — только у тех, кому видны цены; остальное — настройка сотрудника в «Столбцах» (пункт «Т»).
  const columns: DataColumn<SupplierOrderRow>[] = [
    {
      id: "number",
      header: t("orders.columns.number"),
      width: 120,
      cellClassName: "pf-num",
      cell: (row) => (
        <Link className="pf-focusable pf-calc-number" to={row.path}>
          {row.number}
        </Link>
      ),
    },
    {
      id: "supplier",
      header: t("orders.columns.supplier"),
      width: null,
      cellClassName: "pf-ell",
      cellTitle: (row) => row.supplier.name,
      cell: (row) => row.supplier.name,
    },
    {
      id: "requests",
      header: t("orders.columns.requests"),
      width: 160,
      cell: (row) => <Requests row={row} />,
    },
    {
      id: "expected",
      header: t("orders.columns.expected"),
      width: 148,
      cell: (row) => <Expected row={row} />,
    },
    {
      id: "status",
      header: t("orders.columns.status"),
      width: 148,
      cell: (row) => <OrderStatusTag status={row.status} />,
    },
    {
      id: "receipt",
      header: t("orders.columns.receipt"),
      width: 110,
      cell: (row) => <Receipt row={row} />,
    },
    ...(prices
      ? [
          {
            id: "total",
            header: t("orders.columns.total"),
            width: 140,
            numeric: true,
            cell: (row: SupplierOrderRow) => (
              <MoneyText value={row.total} currency={row.currency} />
            ),
          },
        ]
      : []),
    {
      id: "action",
      header: t("orders.columns.action"),
      headerHidden: true,
      width: 120,
      cell: (row) => (
        <LinkButton
          size="small"
          to={row.path}
          aria-label={t("orders.openLabel", { number: row.number })}
        >
          {t("orders.open")}
        </LinkButton>
      ),
    },
  ];
  return (
    <DataTable
      tableId="erp.stock.orders"
      caption={t("orders.caption")}
      scrollLabel={t("orders.scroll")}
      className="pf-calc-table"
      flexMin={160}
      columns={columns}
      rows={items}
      rowKey={(row) => row.number}
    />
  );
}

/** Вкладка «Заказы поставщикам»: ЗП-номер · поставщик · заявки · ожидаемая дата · статус · приёмка · сумма. */
export function OrdersTab() {
  const { t } = useTranslation("stock");
  const labels = useStateLabels();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const status = ORDER_STATUSES.find((s) => s === params.get("status"));
  const overdue = params.get("overdue") === "1";
  const query = useListSupplierOrders({
    ...(status ? { status } : {}),
    ...(overdue ? { overdue: true } : {}),
    ...(q.trim() ? { q: q.trim() } : {}),
  });
  const setParam = (key: string, value: string | null) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true },
    );
  };
  return (
    <>
      <Card styles={{ body: { padding: 0 } }}>
        <div className="pf-stock-toolbar">
          <Input.Search
            allowClear
            aria-label={t("orders.search")}
            placeholder={t("orders.search")}
            onSearch={setQ}
            className="pf-stock-search"
          />
          <Select<SupplierOrderStatus>
            allowClear
            aria-label={t("orders.statusFilter")}
            placeholder={t("orders.statusFilter")}
            value={status}
            onChange={(value) => {
              setParam("status", value);
            }}
            options={ORDER_STATUSES.map((s) => ({ value: s, label: t(`orders.status.${s}`) }))}
            className="pf-stock-select"
          />
          <Checkbox
            checked={overdue}
            onChange={(event) => {
              setParam("overdue", event.target.checked ? "1" : null);
            }}
          >
            {t("orders.overdueOnly")}
          </Checkbox>
          {query.data?.rights.manage ? (
            <Button
              type="primary"
              className="pf-stock-toolbar-action"
              onClick={() => {
                setCreating(true);
              }}
            >
              {t("orders.create")}
            </Button>
          ) : query.isPending ? (
            // До ответа право неизвестно: место кнопки держится, чтобы панель не переносилась, когда она появится (UX-1c, S10)
            <span className="pf-stock-toolbar-action pf-stock-action-slot" aria-hidden="true">
              {t("orders.create")}
            </span>
          ) : null}
        </div>
        <QueryState query={query} labels={labels} rows={10}>
          {(data) =>
            data.items.length === 0 ? (
              <EmptyState
                title={t("orders.empty.title")}
                text={t("orders.empty.text")}
                action={
                  data.rights.manage ? (
                    <Button
                      onClick={() => {
                        setCreating(true);
                      }}
                    >
                      {t("orders.create")}
                    </Button>
                  ) : undefined
                }
              />
            ) : (
              <Rows items={data.items} prices={data.rights.prices} />
            )
          }
        </QueryState>
      </Card>
      {creating ? (
        <OrderCreateModal
          prices={query.data?.rights.prices ?? false}
          onClose={() => {
            setCreating(false);
          }}
        />
      ) : null}
    </>
  );
}
