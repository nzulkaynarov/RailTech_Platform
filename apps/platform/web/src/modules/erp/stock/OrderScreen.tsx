import { Alert, Button, Card, Skeleton } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { PanelPortal } from "../../../app/shell/PanelSlot";
import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type { SupplierOrderDetail } from "../../../shared/api/generated/model";
import { useGetSupplierOrder } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState, ScrollRegion } from "../../../shared/ui/FormParts";
import { History, type HistoryItem } from "../../../shared/ui/History";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { useStateLabels } from "./api";
import { OrderStatusTag } from "./OrdersTab";
import { CancelModal, ConfirmModal, EditModal, ReceiveModal, SendModal } from "./OrderModals";

import "../calc/calc.css";
import "./stock.css";

type Dialog = "send" | "confirm" | "receive" | "cancel" | "edit" | null;

function OrderLog({ order }: { order: SupplierOrderDetail }) {
  const { t } = useTranslation("stock");
  const { activity } = useFormat();
  const items: HistoryItem[] = order.log.map((entry) => ({
    state: "done",
    title: t(`order.log.${entry.kind}`),
    meta: [activity(entry.at), entry.by, entry.detail].filter(Boolean).join(" · "),
  }));
  return <History items={items} label={t("order.log.label")} />;
}

function Lines({ order }: { order: SupplierOrderDetail }) {
  const { t } = useTranslation("stock");
  const { money, number } = useFormat();
  const priced = order.lines.some((l) => l.unit_price !== null);
  return (
    <ScrollRegion label={t("order.lines.scroll")}>
      <table className="pf-calc-table">
        <caption className="pf-sr-only">
          {t("order.lines.caption", { number: order.number })}
        </caption>
        <thead>
          <tr>
            <th scope="col">{t("order.lines.position")}</th>
            <th scope="col">{t("order.lines.request")}</th>
            <th scope="col">{t("order.lines.quantity")}</th>
            <th scope="col">{t("order.lines.received")}</th>
            {priced ? <th scope="col">{t("order.lines.price")}</th> : null}
            {priced ? <th scope="col">{t("order.lines.total")}</th> : null}
          </tr>
        </thead>
        <tbody>
          {order.lines.map((l) => (
            <tr key={l.id}>
              <td>
                <div>{l.name}</div>
                <div className="pf-hint pf-num">{l.article}</div>
              </td>
              <td>
                {l.request ? (
                  <Link className="pf-focusable" to={l.request.path}>
                    {l.request.number}
                  </Link>
                ) : (
                  <span className="pf-hint">—</span>
                )}
              </td>
              <td className="pf-num">
                {number(l.quantity)} {l.unit}
              </td>
              <td className="pf-num">{number(l.received_quantity)}</td>
              {priced ? (
                <td className="pf-num">{l.unit_price ? money(l.unit_price) : "—"}</td>
              ) : null}
              {priced ? (
                <td className="pf-num">{l.line_total ? money(l.line_total) : "—"}</td>
              ) : null}
            </tr>
          ))}
        </tbody>
        {order.total ? (
          <tfoot>
            <tr className="pf-calc-totals">
              <th scope="row" colSpan={priced ? 5 : 4}>
                {t("order.lines.totals")}
              </th>
              <td className="pf-num">
                <strong>{money(order.total)}</strong>
              </td>
            </tr>
          </tfoot>
        ) : null}
      </table>
    </ScrollRegion>
  );
}

function Receipts({ order }: { order: SupplierOrderDetail }) {
  const { t } = useTranslation("stock");
  const { activity } = useFormat();
  if (order.receipts.length === 0)
    return <p className="pf-hint pf-calc-empty">{t("order.receipts.empty")}</p>;
  return (
    <ul className="pf-stock-list pf-stock-list--padded" aria-label={t("order.receipts.label")}>
      {order.receipts.map((r) => (
        <li key={r.id}>
          <span>
            {r.lines
              .map((l) => `${l.name} · ${String(l.quantity)}${l.cell ? ` (${l.cell})` : ""}`)
              .join("; ")}
            {r.supplier_doc ? (
              <span className="pf-hint"> · {t("order.receipts.doc", { doc: r.supplier_doc })}</span>
            ) : null}
          </span>
          <span className="pf-hint">
            {activity(r.received_at)}
            {r.received_by ? ` · ${r.received_by}` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Content({ order }: { order: SupplierOrderDetail }) {
  const { t } = useTranslation("stock");
  const { date, activity } = useFormat();
  const { mobile } = useViewport();
  const [dialog, setDialog] = useState<Dialog>(null);
  const close = () => {
    setDialog(null);
  };
  const a = order.actions;
  const primary = a.send
    ? ("send" as const)
    : a.confirm
      ? ("confirm" as const)
      : a.receive
        ? ("receive" as const)
        : null;
  return (
    <div className="pf-calc pf-stock">
      <PageHeader
        title={t("order.title", { number: order.number })}
        subtitle={[order.supplier.name, order.requests.map((r) => r.number).join(", ")]
          .filter(Boolean)
          .join(" · ")}
        extra={
          <div className="pf-calc-row">
            <OrderStatusTag status={order.status} />
            {primary ? (
              <Button
                type="primary"
                onClick={() => {
                  setDialog(primary);
                }}
              >
                {t(`order.action.${primary}`)}
              </Button>
            ) : null}
            {a.edit ? (
              <Button
                onClick={() => {
                  setDialog("edit");
                }}
              >
                {t("order.action.edit")}
              </Button>
            ) : null}
            {a.cancel ? (
              <Button
                danger
                onClick={() => {
                  setDialog("cancel");
                }}
              >
                {t("order.action.cancel")}
              </Button>
            ) : null}
            <LinkButton to="/erp/stock?view=orders">{t("order.back")}</LinkButton>
          </div>
        }
      />
      {order.overdue && order.days_overdue ? (
        <Alert
          type="warning"
          showIcon
          message={t("order.overdueBanner", {
            date: order.expected_date ? date(order.expected_date) : "",
            count: order.days_overdue,
          })}
        />
      ) : null}
      {order.status === "cancelled" ? (
        <Alert
          type="info"
          showIcon
          message={t("order.cancelledBanner", { reason: order.cancel_reason ?? "—" })}
        />
      ) : null}
      <Card size="small" title={<h2 className="pf-calc-title">{t("order.details")}</h2>}>
        <DefinitionList
          items={[
            { label: t("order.supplier"), value: order.supplier.name },
            { label: t("order.email"), value: order.supplier.email },
            {
              label: t("order.expected"),
              value: order.expected_date ? date(order.expected_date) : null,
            },
            {
              label: t("order.sent"),
              value: order.sent_at
                ? `${activity(order.sent_at)}${order.sent_to ? ` · ${order.sent_to}` : ""}`
                : null,
            },
            {
              label: t("order.confirmed"),
              value: order.confirmed_at ? activity(order.confirmed_at) : null,
            },
            {
              label: t("order.receivedAt"),
              value: order.received_at ? activity(order.received_at) : null,
            },
            { label: t("order.createdBy"), value: order.created_by },
            { label: t("order.note"), value: order.note },
          ]}
        />
      </Card>
      <Card
        size="small"
        title={<h2 className="pf-calc-title">{t("order.linesTitle")}</h2>}
        styles={{ body: { padding: 0 } }}
      >
        <Lines order={order} />
      </Card>
      <Card
        size="small"
        title={<h2 className="pf-calc-title">{t("order.receiptsTitle")}</h2>}
        styles={{ body: { padding: 0 } }}
      >
        <Receipts order={order} />
      </Card>
      <Card size="small" title={<h2 className="pf-calc-title">{t("order.logTitle")}</h2>}>
        <OrderLog order={order} />
      </Card>
      {mobile ? null : (
        <PanelPortal tab="journal">
          <div className="pf-calc-task">
            <h3 className="pf-calc-task-title">{t("order.logTitle")}</h3>
            <OrderLog order={order} />
          </div>
        </PanelPortal>
      )}
      {dialog === "send" ? <SendModal order={order} onClose={close} /> : null}
      {dialog === "confirm" ? <ConfirmModal order={order} onClose={close} /> : null}
      {dialog === "cancel" ? <CancelModal order={order} onClose={close} /> : null}
      {dialog === "edit" ? <EditModal order={order} onClose={close} /> : null}
      {dialog === "receive" ? <ReceiveModal number={order.number} onClose={close} /> : null}
    </div>
  );
}

/**
 * Расчёт · Склад · карточка заказа поставщику «ЗП-…» (SPEC-v3 §7.4): реквизиты, состав с приёмкой, приёмки, журнал; главная
 * кнопка по статусу — «Отправить поставщику» → «Поставщик подтвердил» → «Принять товар», у каждой блок «Что произойдёт».
 */
export function OrderScreen({ number }: { number: string }) {
  const { t } = useTranslation("stock");
  const query = useGetSupplierOrder(encodeURIComponent(number));
  const labels = useStateLabels();
  useDocumentTitle(t("order.title", { number }));
  const error = query.error;
  if (error instanceof ApiError && error.status === 404) {
    return (
      <EmptyState
        title={t("order.notFound.title")}
        text={t("order.notFound.text")}
        action={<LinkButton to="/erp/stock?view=orders">{t("order.notFound.action")}</LinkButton>}
      />
    );
  }
  if (query.isPending) {
    return (
      <div className="pf-calc">
        <Skeleton active paragraph={{ rows: 8 }} />
      </div>
    );
  }
  return (
    <QueryState query={query} labels={labels}>
      {(order) => <Content order={order} />}
    </QueryState>
  );
}
