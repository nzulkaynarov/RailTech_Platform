import { Button, Card, Skeleton } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useSearchParams } from "react-router";

import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type { PaymentCard } from "../../../shared/api/generated/model";
import { listPayments, useGetPayment } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { ScrollRegion } from "../../../shared/ui/FormParts";
import { QueryState } from "../../../shared/ui/FormParts";
import { History, type HistoryItem } from "../../../shared/ui/History";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { InvoiceStatus } from "./InvoiceStatus";
import { InvoiceBrief, PaymentSlot } from "./PaymentPanel";
import { ProofList } from "./ProofsBlock";
import { useStateLabels } from "./labels";
import { invoicePath, isOpen, moneyProps } from "./model";

function Items({ card }: { card: PaymentCard }) {
  const { t } = useTranslation("payments");
  const money = (amount: string) => (
    <MoneyText {...moneyProps({ amount, currency: card.amount.currency })} />
  );
  return (
    <ScrollRegion label={t("items.caption")}>
      <table className="pf-dec-table pf-dec-lines">
        <caption className="pf-sr-only">{t("items.caption")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("items.columns.name")}</th>
            <th scope="col" className="pf-col-num">
              {t("items.columns.quantity")}
            </th>
            <th scope="col" className="pf-col-num">
              {t("items.columns.price")}
            </th>
            <th scope="col" className="pf-col-num">
              {t("items.columns.total")}
            </th>
          </tr>
        </thead>
        <tbody>
          {card.items.map((item, index) => (
            <tr key={index}>
              <td>{item.description}</td>
              <td className="pf-col-num">{item.quantity}</td>
              <td className="pf-col-num">{money(item.unit_price)}</td>
              <td className="pf-col-num">{money(item.total)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={3} className="pf-col-num">
              {t("items.subtotal")}
            </td>
            <td className="pf-col-num">{money(card.subtotal)}</td>
          </tr>
          <tr>
            <td colSpan={3} className="pf-col-num">
              {t("items.vat")}
            </td>
            <td className="pf-col-num">{money(card.vat)}</td>
          </tr>
          <tr>
            <td colSpan={3} className="pf-col-num">
              <strong>{t("items.total")}</strong>
            </td>
            <td className="pf-col-num">
              <MoneyText strong {...moneyProps(card.amount)} />
            </td>
          </tr>
        </tfoot>
      </table>
    </ScrollRegion>
  );
}

function Payments({ card }: { card: PaymentCard }) {
  const { t } = useTranslation("payments");
  const { date } = useFormat();
  if (card.payments.length === 0) return <p className="pf-hint">{t("payments.none")}</p>;
  return (
    <ScrollRegion label={t("payments.caption")}>
      <table className="pf-dec-table">
        <caption className="pf-sr-only">{t("payments.caption")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("payments.columns.date")}</th>
            <th scope="col" className="pf-col-num">
              {t("payments.columns.amount")}
            </th>
            <th scope="col">{t("payments.columns.reference")}</th>
            <th scope="col">{t("payments.columns.by")}</th>
          </tr>
        </thead>
        <tbody>
          {card.payments.map((payment) => (
            <tr key={payment.id}>
              <td className="pf-num">{date(payment.paid_at)}</td>
              <td className="pf-col-num">
                <MoneyText
                  {...moneyProps({ amount: payment.amount, currency: card.amount.currency })}
                />
              </td>
              <td className="pf-num">{payment.reference || "—"}</td>
              <td>{payment.recorded_by ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}

function Log({ card }: { card: PaymentCard }) {
  const { t, i18n } = useTranslation("payments");
  const { date } = useFormat();
  if (card.history.length === 0) return <p className="pf-hint">{t("history.empty")}</p>;
  const items: HistoryItem[] = card.history.map((entry) => ({
    state: "done",
    title: i18n.exists(`payments:history.code.${entry.code.replace(".", "_")}`)
      ? t(`history.code.${entry.code.replace(".", "_")}`)
      : entry.text,
    meta: `${date(entry.at, "datetime")}${entry.by ? ` · ${entry.by}` : ""}`,
  }));
  return <History items={items} label={t("history.title")} />;
}

function Content({ card }: { card: PaymentCard }) {
  const { t } = useTranslation("payments");
  const { me } = useAuth();
  const { wide, mobile } = useViewport();
  const [, setParams] = useSearchParams();
  const mayAct = me.resources["eds.payments"] === "full" && card.can_confirm;
  const openPanel = () => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (mobile) next.set("sheet", "payment");
        else next.set("panel", "open");
        next.set("tab", "payment");
        return next;
      },
      { replace: true },
    );
  };
  return (
    <div className="pf-dec-page">
      <PageHeader
        title={card.number}
        subtitle={t("view.projectLine", { project: card.project_number, client: card.client_name })}
        extra={
          <div className="pf-dec-row">
            <InvoiceStatus status={card.status} />
            <LinkButton to="/eds/payments">{t("view.back")}</LinkButton>
          </div>
        }
      />
      {mayAct && !wide ? (
        <div>
          <Button type="primary" onClick={openPanel}>
            {t("confirm.name")}
          </Button>
        </div>
      ) : null}
      {isOpen(card.status) && !mayAct ? (
        <p className="pf-hint">{t("panel.readOnly.text")}</p>
      ) : null}
      <div className="pf-dec-grid">
        <div className="pf-dec-main">
          <Card size="small" title={<h2 className="pf-dec-title">{t("items.title")}</h2>}>
            <Items card={card} />
          </Card>
          <Card size="small" title={<h2 className="pf-dec-title">{t("payments.title")}</h2>}>
            <Payments card={card} />
          </Card>
          <Card size="small" title={<h2 className="pf-dec-title">{t("proofs.title")}</h2>}>
            <ProofList card={card} />
          </Card>
          <Card size="small" title={<h2 className="pf-dec-title">{t("history.title")}</h2>}>
            <Log card={card} />
          </Card>
        </div>
        <aside className="pf-dec-side" aria-label={t("brief.amount")}>
          <InvoiceBrief card={card} />
        </aside>
      </div>
      <PaymentSlot invoiceId={card.id} />
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
