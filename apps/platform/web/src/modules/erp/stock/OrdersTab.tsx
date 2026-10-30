import { Button, Card, Checkbox, Input, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { useViewport } from "../../../app/shell/useViewport";
import type { SupplierOrderRow, SupplierOrderStatus } from "../../../shared/api/generated/model";
import { useListSupplierOrders } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { TableCols } from "../../../shared/ui/DataBlock";
import { tableMinWidth } from "../../../shared/ui/tableWidth";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState, ScrollRegion } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { ORDER_STATUSES, ORDER_TONE, useStateLabels } from "./api";
import { OrderCreateModal } from "./OrderCreateModal";

/** Ширины колонок: номер, поставщик (гибкая), заявки, ожидается, статус, приёмка, [сумма], действие (UX-1c, S9) */
const colsOf = (prices: boolean) =>
  prices
    ? ([120, null, 140, 130, 140, 110, 140, 120] as const)
    : ([120, null, 140, 130, 140, 110, 120] as const);

export function OrderStatusTag({ status }: { status: SupplierOrderStatus }) {
  const { t } = useTranslation("stock");
  return <StatusTag tone={ORDER_TONE[status]}>{t(`orders.status.${status}`)}</StatusTag>;
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
  const { money } = useFormat();
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
  return (
    <ScrollRegion label={t("orders.scroll")}>
      <table
        className="pf-calc-table pf-fixed-table"
        style={{ minWidth: tableMinWidth(colsOf(prices), 160) }}
      >
        <caption className="pf-sr-only">{t("orders.caption")}</caption>
        <TableCols widths={colsOf(prices)} />
        <thead>
          <tr>
            <th scope="col">{t("orders.columns.number")}</th>
            <th scope="col">{t("orders.columns.supplier")}</th>
            <th scope="col">{t("orders.columns.requests")}</th>
            <th scope="col">{t("orders.columns.expected")}</th>
            <th scope="col">{t("orders.columns.status")}</th>
            <th scope="col">{t("orders.columns.receipt")}</th>
            {prices ? <th scope="col">{t("orders.columns.total")}</th> : null}
            <th scope="col">
              <span className="pf-sr-only">{t("orders.columns.action")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <tr key={row.number}>
              <td className="pf-num">
                <Link className="pf-focusable pf-calc-number" to={row.path}>
                  {row.number}
                </Link>
              </td>
              <td className="pf-ell" title={row.supplier.name}>
                {row.supplier.name}
              </td>
              <td>
                <Requests row={row} />
              </td>
              <td>
                <Expected row={row} />
              </td>
              <td>
                <OrderStatusTag status={row.status} />
              </td>
              <td>
                <Receipt row={row} />
              </td>
              {prices ? <td className="pf-num">{row.total ? money(row.total) : "—"}</td> : null}
              <td>
                <LinkButton
                  size="small"
                  to={row.path}
                  aria-label={t("orders.openLabel", { number: row.number })}
                >
                  {t("orders.open")}
                </LinkButton>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
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
