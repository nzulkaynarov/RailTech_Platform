import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { useAuth } from "../../../app/auth/useAuth";
import type { PaymentCard } from "../../../shared/api/generated/model";
import { useGetPayment } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { DecisionSlot } from "../decision/DecisionSlot";
import { ConfirmForm } from "./ConfirmForm";
import { InvoiceStatus } from "./InvoiceStatus";
import { ProofsBlock } from "./ProofsBlock";
import { useStateLabels } from "./labels";
import { invoicePath, isOpen, moneyProps } from "./model";

/** Реквизиты счёта для панели и страницы: клиент, проект, суммы, остаток, срок (просрочка — словом, не только цветом). */
export function InvoiceBrief({ card, link = false }: { card: PaymentCard; link?: boolean }) {
  const { t } = useTranslation("payments");
  const { date } = useFormat();
  return (
    <section className="pf-dec-brief" aria-label={card.number}>
      <div className="pf-dec-brief-head">
        <h3 className="pf-fp-title">{card.number}</h3>
        <InvoiceStatus status={card.status} />
      </div>
      <DefinitionList
        items={[
          { label: t("brief.client"), value: card.client_name },
          { label: t("brief.project"), value: card.project_number },
          { label: t("brief.amount"), value: <MoneyText {...moneyProps(card.amount)} /> },
          { label: t("brief.paid"), value: <MoneyText {...moneyProps(card.paid)} /> },
          {
            label: t("brief.balance"),
            value: <MoneyText strong {...moneyProps(card.balance)} />,
          },
          { label: t("brief.issued"), value: card.issued_at ? date(card.issued_at) : null },
          {
            label: t("brief.due"),
            value: card.due_date ? (
              <>
                {date(card.due_date)}
                {card.days_overdue ? (
                  <span className="pf-pay-overdue">
                    {" · "}
                    {t("list.overdueDays", { count: card.days_overdue })}
                  </span>
                ) : null}
              </>
            ) : null,
          },
        ]}
      />
      {link ? (
        <Link className="pf-focusable pf-dec-open" to={invoicePath(card.id)}>
          {t("panel.open")}
        </Link>
      ) : null}
    </section>
  );
}

function Body({
  card,
  variant,
  brief,
  onDone,
}: {
  card: PaymentCard;
  variant: "panel" | "sheet";
  brief: boolean;
  onDone?: (() => void) | undefined;
}) {
  const { t } = useTranslation("payments");
  const { me } = useAuth();
  const mayAct = me.resources["eds.payments"] === "full";
  let action: ReactNode;
  if (!isOpen(card.status)) {
    const closed =
      card.status === "paid" ? "paid" : card.status === "draft" ? "draft" : "cancelled";
    action = (
      <EmptyState
        level={3}
        compact
        title={t(`panel.closed.${closed}.title`)}
        text={t(`panel.closed.${closed}.text`)}
      />
    );
  } else if (card.can_confirm && mayAct) {
    // Форма начинается заново, когда карточка изменилась по существу (остаток, число платёжек на подтверждении).
    const formKey = `${card.balance.amount}:${String(card.proofs.filter((p) => p.status === "PENDING").length)}`;
    action = (
      <ConfirmForm key={formKey} card={card} variant={variant} {...(onDone ? { onDone } : {})} />
    );
  } else {
    action = (
      <EmptyState
        level={3}
        compact
        title={t("panel.readOnly.title")}
        text={t("panel.readOnly.text")}
      />
    );
  }
  return (
    <div className="pf-dec-panel pf-dec-page">
      {brief ? <InvoiceBrief card={card} link /> : null}
      {action}
      <ProofsBlock card={card} />
    </div>
  );
}

/** Содержимое вкладки «Оплата»: счёт, форма «Подтвердить оплату», платёжки клиента (SPEC-v3 §7.3 «Вкладка Оплата»). */
export function PaymentPanel({
  invoiceId,
  brief = false,
  variant = "panel",
  onDone,
}: {
  invoiceId: number;
  brief?: boolean;
  variant?: "panel" | "sheet";
  onDone?: (() => void) | undefined;
}) {
  const query = useGetPayment(invoiceId);
  const labels = useStateLabels();
  return (
    <QueryState query={query} labels={labels} level={3} compact>
      {(card) => <Body card={card} variant={variant} brief={brief} onDone={onDone} />}
    </QueryState>
  );
}

function SheetTitle({ invoiceId }: { invoiceId: number }) {
  const { t } = useTranslation("payments");
  const query = useGetPayment(invoiceId);
  return (
    <>{query.data ? t("panel.sheetTitle", { number: query.data.number }) : t("panel.sheetLabel")}</>
  );
}

/** Где живёт «Оплата»: вкладка бокового окна каркаса, на телефоне — лист на весь экран (`?sheet=payment`). */
export function PaymentSlot({ invoiceId, brief = false }: { invoiceId: number; brief?: boolean }) {
  const { t } = useTranslation("payments");
  return (
    <DecisionSlot
      tab="payment"
      sheet="payment"
      title={<SheetTitle invoiceId={invoiceId} />}
      label={t("panel.sheetLabel")}
      closeLabel={t("panel.sheetClose")}
    >
      {(variant, onDone) => (
        <PaymentPanel invoiceId={invoiceId} brief={brief} variant={variant} onDone={onDone} />
      )}
    </DecisionSlot>
  );
}
