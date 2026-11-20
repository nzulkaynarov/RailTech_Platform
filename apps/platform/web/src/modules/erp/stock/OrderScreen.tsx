import { Alert, Button, Card, Skeleton } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { PanelPortal } from "../../../app/shell/PanelSlot";
import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type { SupplierOrderDetail, SupplierOrderMail } from "../../../shared/api/generated/model";
import { useGetSupplierOrder } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { DataTable, type DataColumn } from "../../../shared/ui/DataTable/DataTable";
import { History, type HistoryItem } from "../../../shared/ui/History";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { useStateLabels, withUnit } from "./api";
import { OrderStatusTag } from "./OrdersTab";
import { CancelModal, ConfirmModal, EditModal, ReceiveModal, SendModal } from "./OrderModals";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { ItemRefCell } from "../../ItemRefCell";

import "../calc/calc.css";
import "./stock.css";
import { PersonRefCell } from "../../PersonRefCell";

type Dialog = "send" | "confirm" | "receive" | "cancel" | "edit" | null;

function OrderLog({ order }: { order: SupplierOrderDetail }) {
  const { t } = useTranslation("stock");
  const { activity } = useFormat();
  const items: HistoryItem[] = order.log.map((entry) => ({
    state: "done",
    title: t(`order.log.${entry.kind}`),
    meta: [activity(entry.at), entry.by?.name, entry.detail].filter(Boolean).join(" · "),
  }));
  return <History items={items} label={t("order.log.label")} />;
}

/** Цена поставщика, из которой создана строка (ADR-0021 п. 6): базис поставки и срок цены. */
function OfferNote({
  offer,
}: {
  offer: NonNullable<SupplierOrderDetail["lines"][number]["offer"]>;
}) {
  const { t } = useTranslation("stock");
  const { date } = useFormat();
  const parts = [
    offer.incoterms ? t("order.offer.incoterms", { code: offer.incoterms }) : null,
    offer.valid_until
      ? t(offer.expired ? "order.offer.expired" : "order.offer.validUntil", {
          date: date(offer.valid_until),
        })
      : null,
  ].filter(Boolean);
  if (parts.length === 0) return null;
  return <div className="pf-hint">{t("order.offer.label", { text: parts.join(" · ") })}</div>;
}

function Lines({ order }: { order: SupplierOrderDetail }) {
  const { t } = useTranslation("stock");
  const { qty } = useFormat();
  const priced = order.lines.some((l) => l.unit_price !== null);
  type Line = SupplierOrderDetail["lines"][number];
  const columns: DataColumn<Line>[] = [
    {
      id: "position",
      header: t("order.lines.position"),
      width: null,
      cell: (l) => (
        <>
          <ItemRefCell item={l.item} name={l.name} />
          {l.offer ? <OfferNote offer={l.offer} /> : null}
        </>
      ),
    },
    {
      id: "request",
      header: t("order.lines.request"),
      width: 140,
      cell: (l) =>
        l.request ? (
          <Link className="pf-focusable" to={l.request.path}>
            {l.request.number}
          </Link>
        ) : (
          <span className="pf-hint">—</span>
        ),
    },
    {
      id: "quantity",
      header: t("order.lines.quantity"),
      width: 120,
      numeric: true,
      cell: (l) => withUnit(qty(l.quantity), l.unit),
    },
    {
      id: "received",
      header: t("order.lines.received"),
      width: 110,
      numeric: true,
      cell: (l) => withUnit(qty(l.received_quantity), l.unit),
    },
    ...(priced
      ? [
          {
            id: "price",
            header: t("order.lines.price"),
            width: 140,
            numeric: true,
            cell: (l: Line) => <MoneyText value={l.unit_price} currency={order.currency} />,
          },
          {
            id: "total",
            header: t("order.lines.total"),
            width: 150,
            numeric: true,
            cell: (l: Line) => <MoneyText value={l.line_total} currency={order.currency} />,
          },
        ]
      : []),
  ];
  return (
    <>
      <DataTable<Line>
        tableId="erp.stock.orderLines"
        caption={t("order.lines.caption", { number: order.number })}
        scrollLabel={t("order.lines.scroll")}
        className="pf-calc-table"
        rows={order.lines}
        rowKey={(l) => l.id}
        columns={columns}
        toolsTarget={null}
      />
      {order.total ? (
        <div className="pf-table-totals">
          <DefinitionList
            items={[
              {
                label: t("order.lines.totals"),
                value: <MoneyText value={order.total} currency={order.currency} strong />,
              },
            ]}
          />
        </div>
      ) : null}
    </>
  );
}

function Receipts({ order }: { order: SupplierOrderDetail }) {
  const { t } = useTranslation("stock");
  const { activity, qty } = useFormat();
  if (order.receipts.length === 0)
    return <p className="pf-hint pf-calc-empty">{t("order.receipts.empty")}</p>;
  return (
    <ul className="pf-stock-list pf-stock-list--padded" aria-label={t("order.receipts.label")}>
      {order.receipts.map((r) => (
        <li key={r.id}>
          <span>
            {r.lines
              .map((l) => {
                const unit = order.lines.find((x) => x.id === l.order_line_id)?.unit;
                return `${l.name} · ${withUnit(qty(l.quantity), unit)}${l.cell ? ` (${l.cell})` : ""}`;
              })
              .join("; ")}
            {r.supplier_doc ? (
              <span className="pf-hint"> · {t("order.receipts.doc", { doc: r.supplier_doc })}</span>
            ) : null}
          </span>
          <span className="pf-hint">
            {activity(r.received_at)}
            {r.received_by ? ` · ${r.received_by.name}` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Итог письма партнёру словами (0.10, FR-12); причина — из общего словаря журнала почты (`integrations:mail.reason`). */
function useMailText() {
  const { t, i18n } = useTranslation(["stock", "integrations"]);
  return (mail: SupplierOrderMail): string => {
    if (mail.state === "queued") return t("stock:order.mail.queued");
    if (mail.state === "sent") return t("stock:order.mail.sent");
    const key = `mail.reason.${mail.reason ?? ""}`;
    return mail.reason && i18n.exists(key, { ns: "integrations" })
      ? t("stock:order.mail.failed", { reason: t(`integrations:${key}`) })
      : t("stock:order.mail.failedUnknown");
  };
}

function Content({ order }: { order: SupplierOrderDetail }) {
  const { t } = useTranslation("stock");
  const mailText = useMailText();
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
            // 0.10 (FR-12): итог письма приходит от почтового сервиса — «отправлено» только после него.
            { label: t("order.mail.label"), value: order.mail ? mailText(order.mail) : null },
            {
              label: t("order.confirmed"),
              value: order.confirmed_at ? activity(order.confirmed_at) : null,
            },
            {
              label: t("order.receivedAt"),
              value: order.received_at ? activity(order.received_at) : null,
            },
            {
              label: t("order.createdBy"),
              value: order.created_by ? <PersonRefCell person={order.created_by} /> : null,
            },
            {
              label: t("order.partnerNote"),
              value: order.partner_note ? (
                <span className="pf-stock-multiline">{order.partner_note}</span>
              ) : null,
            },
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
