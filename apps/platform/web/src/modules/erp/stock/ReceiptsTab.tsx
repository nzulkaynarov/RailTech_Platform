import { Button, Card } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { useViewport } from "../../../app/shell/useViewport";
import type { StockPendingReceiptLine } from "../../../shared/api/generated/model";
import { useListStockReceipts } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DataTable, type DataColumn } from "../../../shared/ui/DataTable/DataTable";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { useStateLabels } from "./api";
import { ReceiveModal } from "./OrderModals";

/** Ширины колонок: заказ, поставщик, позиция (гибкая), осталось, ожидается, действие (UX-1c, S9) */
const COLS = {
  order: 140,
  supplier: 200,
  left: 156,
  expected: 140,
  action: 150,
};

function Pending({
  items,
  manage,
  onReceive,
}: {
  items: readonly StockPendingReceiptLine[];
  manage: boolean;
  onReceive: (line: StockPendingReceiptLine) => void;
}) {
  const { t } = useTranslation("stock");
  const { date } = useFormat();
  const { mobile } = useViewport();
  const action = (line: StockPendingReceiptLine) =>
    manage ? (
      <Button
        size="small"
        aria-label={t("receipts.receiveLabel", { name: line.name, number: line.order_number })}
        onClick={() => {
          onReceive(line);
        }}
      >
        {t("receipts.receive")}
      </Button>
    ) : null;
  const when = (line: StockPendingReceiptLine) =>
    line.expected_date ? (
      <span className="pf-calc-due">
        <span className="pf-num">{date(line.expected_date)}</span>
        {line.overdue ? <StatusTag tone="red">{t("receipts.overdue")}</StatusTag> : null}
      </span>
    ) : (
      <span className="pf-hint">—</span>
    );
  if (mobile) {
    return (
      <ul className="pf-calc-cards" aria-label={t("receipts.pendingCaption")}>
        {items.map((line) => (
          <li key={`${line.order_number}:${line.order_line_id}`}>
            <div className="pf-calc-card-head">
              <Link className="pf-focusable pf-calc-number" to={line.order_path}>
                {line.order_number}
              </Link>
              {when(line)}
            </div>
            <p className="pf-calc-card-title">{line.name}</p>
            <p className="pf-hint">
              {line.supplier} ·{" "}
              {t("receipts.left", {
                left: line.quantity - line.received_quantity,
                total: line.quantity,
              })}
            </p>
            <div className="pf-calc-card-foot">{action(line)}</div>
          </li>
        ))}
      </ul>
    );
  }
  // Ширины по типу (COLS, T1); остальное — настройка сотрудника в «Столбцах» (пункт «Т»).
  const columns: DataColumn<StockPendingReceiptLine>[] = [
    {
      id: "order",
      header: t("receipts.columns.order"),
      width: COLS.order,
      cellClassName: "pf-num",
      cell: (line) => (
        <>
          <Link className="pf-focusable pf-calc-number" to={line.order_path}>
            {line.order_number}
          </Link>
        </>
      ),
    },
    {
      id: "supplier",
      header: t("receipts.columns.supplier"),
      width: COLS.supplier,
      cellClassName: "pf-ell",
      cellTitle: (line) => line.supplier,
      cell: (line) => line.supplier,
    },
    {
      id: "position",
      header: t("receipts.columns.position"),
      width: null,
      cell: (line) => (
        <>
          <div>{line.name}</div>
          <div className="pf-hint pf-num">{line.article}</div>
        </>
      ),
    },
    {
      id: "left",
      header: t("receipts.columns.left"),
      width: COLS.left,
      numeric: true,
      cell: (line) => (
        <>
          {t("receipts.left", {
            left: line.quantity - line.received_quantity,
            total: line.quantity,
          })}
        </>
      ),
    },
    {
      id: "expected",
      header: t("receipts.columns.expected"),
      width: COLS.expected,
      cell: (line) => when(line),
    },
    {
      id: "action",
      header: t("receipts.columns.action"),
      headerHidden: true,
      width: COLS.action,
      cell: (line) => action(line),
    },
  ];
  return (
    <DataTable
      tableId="erp.stock.receipts"
      caption={t("receipts.pendingCaption")}
      scrollLabel={t("receipts.pendingScroll")}
      className="pf-calc-table"
      flexMin={220}
      columns={columns}
      rows={items}
      rowKey={(line) => `${line.order_number}:${line.order_line_id}`}
    />
  );
}

/** Вкладка «Приёмка»: строки подтверждённых заказов, которые ждут товара, и последние приёмки. */
export function ReceiptsTab() {
  const { t } = useTranslation("stock");
  const { activity } = useFormat();
  const labels = useStateLabels();
  const query = useListStockReceipts();
  const [receiving, setReceiving] = useState<StockPendingReceiptLine | null>(null);
  return (
    <div className="pf-calc-stack">
      <QueryState query={query} labels={labels} rows={10}>
        {(data) => (
          <>
            <Card
              size="small"
              title={<h2 className="pf-calc-title">{t("receipts.pendingTitle")}</h2>}
              styles={{ body: { padding: 0 } }}
            >
              {data.pending.length === 0 ? (
                <EmptyState title={t("receipts.empty.title")} text={t("receipts.empty.text")} />
              ) : (
                <Pending
                  items={data.pending}
                  manage={data.rights.manage}
                  onReceive={setReceiving}
                />
              )}
            </Card>
            <Card
              size="small"
              title={<h2 className="pf-calc-title">{t("receipts.doneTitle")}</h2>}
              styles={{ body: { padding: 0 } }}
            >
              {data.done.length === 0 ? (
                <p className="pf-hint pf-calc-empty">{t("receipts.doneEmpty")}</p>
              ) : (
                <ul
                  className="pf-stock-list pf-stock-list--padded"
                  aria-label={t("receipts.doneTitle")}
                >
                  {data.done.map((r) => (
                    <li key={r.id}>
                      <span>
                        <Link className="pf-focusable" to={r.order_path}>
                          {r.order_number}
                        </Link>
                        <span className="pf-hint">
                          {" "}
                          · {r.supplier} ·{" "}
                          {r.lines
                            .map(
                              (l) =>
                                `${l.name} ${String(l.quantity)}${l.cell ? ` (${l.cell})` : ""}`,
                            )
                            .join("; ")}
                          {r.supplier_doc ? ` · ${t("receipts.doc", { doc: r.supplier_doc })}` : ""}
                        </span>
                      </span>
                      <span className="pf-hint">
                        {activity(r.received_at)}
                        {r.received_by ? ` · ${r.received_by}` : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </>
        )}
      </QueryState>
      {receiving ? (
        <ReceiveModal
          number={receiving.order_number}
          line={receiving.order_line_id}
          onClose={() => {
            setReceiving(null);
          }}
        />
      ) : null}
    </div>
  );
}
