import { Card, Skeleton } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router";

import { ApiError } from "../../../shared/api/errors";
import type { PaymentCard } from "../../../shared/api/generated/model";
import { listPayments, useGetPayment } from "../../../shared/api/generated/platform-bff";
import { formatQuantity } from "../../../shared/lib/money";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { DataTable } from "../../../shared/ui/DataTable/DataTable";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { QueryState } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { RecordHistory, type RecordHistoryEntry } from "../../../shared/ui/RecordHistory";
import { DecisionCenter } from "../decision/DecisionCenter";
import { RecordTab } from "../decision/RecordTab";
import { InvoiceStatus } from "./InvoiceStatus";
import { InvoiceFacts, PaymentPanel } from "./PaymentPanel";
import { ProofsBlock } from "./ProofsBlock";
import { useStateLabels } from "./labels";
import { invoicePath, moneyProps } from "./model";

type Line = PaymentCard["items"][number];
type Paid = PaymentCard["payments"][number];

/** Строки счёта — общая таблица без «Столбцов» (стандарт §7), итоги — списком под ней, как в КП. */
function Items({ card }: { card: PaymentCard }) {
  const { t, i18n } = useTranslation("payments");
  // ADR-0027 п. 9, 10: дробное количество и единица строки — «12,5 т».
  const quantity = (item: Line) =>
    [formatQuantity(item.quantity, { language: i18n.language }), item.unit]
      .filter(Boolean)
      .join("\u00a0");
  const money = (amount: string) => (
    <MoneyText {...moneyProps({ amount, currency: card.amount.currency })} />
  );
  return (
    <>
      <DataTable<Line>
        tableId="eds.payment.items"
        caption={t("items.caption")}
        scrollLabel={t("items.caption")}
        className="pf-dec-table pf-dec-lines"
        rows={card.items}
        rowKey={(item) => String(card.items.indexOf(item))}
        toolsTarget={null}
        columns={[
          {
            id: "name",
            header: t("items.columns.name"),
            width: null,
            cell: (item) => item.description,
          },
          {
            id: "quantity",
            header: t("items.columns.quantity"),
            width: 96,
            numeric: true,
            cell: quantity,
          },
          {
            id: "price",
            header: t("items.columns.price"),
            width: 160,
            numeric: true,
            cell: (item) => money(item.unit_price),
          },
          {
            id: "total",
            header: t("items.columns.total"),
            width: 160,
            numeric: true,
            cell: (item) => money(item.total),
          },
        ]}
      />
      <div className="pf-table-totals">
        <DefinitionList
          items={[
            { label: t("items.subtotal"), value: money(card.subtotal) },
            { label: t("items.vat"), value: money(card.vat) },
            {
              label: t("items.total"),
              value: <MoneyText strong {...moneyProps(card.amount)} />,
            },
          ]}
        />
      </div>
    </>
  );
}

function Payments({ card }: { card: PaymentCard }) {
  const { t } = useTranslation("payments");
  const { date } = useFormat();
  if (card.payments.length === 0) return <p className="pf-hint">{t("payments.none")}</p>;
  return (
    <DataTable<Paid>
      tableId="eds.payment.payments"
      caption={t("payments.caption")}
      scrollLabel={t("payments.caption")}
      className="pf-dec-table"
      rows={card.payments}
      rowKey={(payment) => String(payment.id)}
      toolsTarget={null}
      columns={[
        {
          id: "date",
          header: t("payments.columns.date"),
          width: 120,
          cellClassName: "pf-num",
          cell: (payment) => date(payment.paid_at),
        },
        {
          id: "amount",
          header: t("payments.columns.amount"),
          width: 160,
          numeric: true,
          cell: (payment) => (
            <MoneyText
              {...moneyProps({ amount: payment.amount, currency: card.amount.currency })}
            />
          ),
        },
        {
          id: "reference",
          header: t("payments.columns.reference"),
          width: null,
          cellClassName: "pf-num",
          cell: (payment) => payment.reference || "—",
        },
        {
          id: "by",
          header: t("payments.columns.by"),
          width: 180,
          cell: (payment) => payment.recorded_by ?? "—",
        },
      ]}
    />
  );
}

function Content({ card }: { card: PaymentCard }) {
  const { t, i18n } = useTranslation("payments");
  const history: RecordHistoryEntry[] = card.history.map((entry) => {
    const key = `history.code.${entry.code.replace(".", "_")}`;
    return {
      at: entry.at,
      by: entry.by ?? null,
      action: i18n.exists(`payments:${key}`) ? t(key) : entry.text,
    };
  });
  return (
    <div className="pf-dec-page pf-overlay-aware">
      <PageHeader
        title={card.number}
        extra={
          <div className="pf-dec-row">
            <InvoiceStatus status={card.status} />
            <LinkButton to="/eds/payments">{t("view.back")}</LinkButton>
          </div>
        }
      />
      <Card size="small" title={<h2 className="pf-dec-title">{t("items.title")}</h2>}>
        <Items card={card} />
      </Card>
      <Card size="small" title={<h2 className="pf-dec-title">{t("payments.title")}</h2>}>
        <Payments card={card} />
      </Card>
      <Card size="small" title={<h2 className="pf-dec-title">{t("proofs.title")}</h2>}>
        <ProofsBlock card={card} heading={false} />
      </Card>
      <DecisionCenter legacyTab="payment" legacySheet="payment" label={t("panel.sheetLabel")}>
        <PaymentPanel invoiceId={card.id} />
      </DecisionCenter>
      <RecordTab tab="facts">
        <InvoiceFacts card={card} />
      </RecordTab>
      {history.length > 0 ? (
        <RecordTab tab="history">
          <RecordHistory label={t("history.title")} entries={history} />
        </RecordTab>
      ) : null}
    </div>
  );
}

/** Карточка счёта (SPEC-v3 §7.3 «Вкладка Оплата»): состав, оплаты, платёжки, журнал; «Подтвердить оплату» — в боковом окне. */
export function PaymentView({ id }: { id: number }) {
  const { t } = useTranslation("payments");
  const query = useGetPayment(id);
  const labels = useStateLabels();
  useDocumentTitle(query.data?.number ?? String(id));
  const error = query.error;
  if (error instanceof ApiError && error.status === 404) {
    return (
      <EmptyState
        title={t("state.notFound.title")}
        text={t("state.notFound.text")}
        action={<LinkButton to="/eds/payments">{t("state.notFound.action")}</LinkButton>}
      />
    );
  }
  if (error instanceof ApiError && error.status === 403 && error.source === "erp") {
    return (
      <EmptyState
        title={t("state.erpForbidden.title")}
        text={t("state.erpForbidden.text")}
        action={<LinkButton to="/eds/payments?show=memos">{t("list.tabs.memos")}</LinkButton>}
      />
    );
  }
  if (query.isPending) {
    return (
      <div className="pf-dec-page">
        <Skeleton active paragraph={{ rows: 6 }} />
      </div>
    );
  }
  return (
    <QueryState query={query} labels={labels}>
      {(card) => <Content card={card} />}
    </QueryState>
  );
}

/**
 * Адрес по номеру счёта (`/eds/payments/СЧ-2026%2F142`, ссылки из очереди и поиска): ERP ищет счёт по номеру, а экран
 * переходит на карточку по id; не нашёл — «Счёт не найден».
 */
export function PaymentByNumber({ number }: { number: string }) {
  const { t } = useTranslation("payments");
  const navigate = useNavigate();
  const { search } = useLocation();
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    let cancelled = false;
    listPayments({ tab: "all", q: number, limit: 5 })
      .then((board) => {
        if (cancelled) return;
        const hit = board.items.find((row) => row.number === number);
        if (hit) void navigate(`${invoicePath(hit.id)}${search}`, { replace: true });
        else setMissing(true);
      })
      .catch(() => {
        if (!cancelled) setMissing(true);
      });
    return () => {
      cancelled = true;
    };
  }, [number, navigate, search]);
  if (missing) {
    return (
      <EmptyState
        title={t("state.notFound.title")}
        text={t("state.notFound.text")}
        action={<LinkButton to="/eds/payments">{t("state.notFound.action")}</LinkButton>}
      />
    );
  }
  return (
    <div className="pf-dec-page">
      <Skeleton active paragraph={{ rows: 4 }} />
    </div>
  );
}
