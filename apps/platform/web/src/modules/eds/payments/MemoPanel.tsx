import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { PaymentMemoCard } from "../../../shared/api/generated/model";
import {
  getDownloadEdsDocumentFileUrl,
  useGetPaymentMemo,
} from "../../../shared/api/generated/platform-bff";
import { formatFileSize } from "../../../shared/lib/fileSize";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { DecisionSlot } from "../decision/DecisionSlot";
import { PayMemoForm } from "./PayMemoForm";
import { useStateLabels } from "./labels";
import { memoPath, moneyProps } from "./model";

export function MemoFiles({ memo }: { memo: PaymentMemoCard }) {
  const { t, i18n } = useTranslation("payments");
  if (memo.files.length === 0) return <p className="pf-hint">{t("memo.panel.noFiles")}</p>;
  return (
    <ul className="pf-dec-list" aria-label={t("memo.panel.files")}>
      {memo.files.map((file) => (
        <li key={file.id}>
          <a
            className="pf-focusable pf-dec-link"
            href={getDownloadEdsDocumentFileUrl(file.id)}
            download
            aria-label={t("memo.panel.download", { name: file.name })}
          >
            {file.name}
          </a>
          <span className="pf-hint">{formatFileSize(file.size, i18n.language)}</span>
        </li>
      ))}
    </ul>
  );
}

export function MemoStatus({ status }: { status: PaymentMemoCard["status"] }) {
  const { t } = useTranslation("payments");
  if (status === "other") return null;
  return (
    <StatusTag tone={status === "paid" ? "green" : "blue"}>{t(`memo.status.${status}`)}</StatusTag>
  );
}

function Brief({ memo, link }: { memo: PaymentMemoCard; link: boolean }) {
  const { t } = useTranslation("payments");
  const { date } = useFormat();
  const label = memo.number ?? memo.subject;
  return (
    <section className="pf-dec-brief" aria-label={label}>
      <div className="pf-dec-brief-head">
        <h3 className="pf-fp-title">{label}</h3>
        <MemoStatus status={memo.status} />
      </div>
      <p className="pf-dec-subject">{memo.subject}</p>
      <DefinitionList
        items={[
          { label: t("memo.panel.from"), value: memo.author.full_name },
          {
            label: t("memo.panel.amount"),
            value: memo.amount ? <MoneyText {...moneyProps(memo.amount)} /> : null,
          },
          { label: t("memo.panel.due"), value: memo.due_date ? date(memo.due_date) : null },
        ]}
      />
      <h4 className="pf-dec-subhead">{t("memo.panel.files")}</h4>
      <MemoFiles memo={memo} />
      {link ? (
        <Link className="pf-focusable pf-dec-open" to={memoPath(memo.id)}>
          {t("memo.panel.open")}
        </Link>
      ) : null}
    </section>
  );
}

function PaidSummary({ memo }: { memo: PaymentMemoCard }) {
  const { t } = useTranslation("payments");
  const { date, money } = useFormat();
  const payment = memo.payment;
  if (!payment) return null;
  const receipt = memo.files.find((f) => f.id === payment.receipt_file_id);
  return (
    <EmptyState
      level={3}
      compact
      title={t("memo.panel.paidTitle")}
      text={t("memo.panel.paidText", {
        date: date(payment.paid_on),
        amount: money(payment.amount.amount, { currency: payment.amount.currency }),
      })}
      action={
        receipt ? (
          <a
            className="pf-focusable pf-dec-link"
            href={getDownloadEdsDocumentFileUrl(receipt.id)}
            download
            aria-label={t("memo.panel.download", { name: receipt.name })}
          >
            {t("memo.panel.receipt")}: {receipt.name}
          </a>
        ) : undefined
      }
    />
  );
}

function Body({
  memo,
  variant,
  brief,
  onDone,
}: {
  memo: PaymentMemoCard;
  variant: "panel" | "sheet";
  brief: boolean;
  onDone?: (() => void) | undefined;
}) {
  const { t } = useTranslation("payments");
  let action;
  if (memo.payment) action = <PaidSummary memo={memo} />;
  else if (memo.can_pay)
    action = <PayMemoForm memo={memo} variant={variant} {...(onDone ? { onDone } : {})} />;
  else if (memo.status === "to_pay") {
    action = (
      <EmptyState
        level={3}
        compact
        title={t("memo.panel.readOnly.title")}
        text={t("memo.panel.readOnly.text")}
      />
    );
  } else {
    action = null;
  }
  return (
    <div className="pf-dec-panel pf-dec-page">
      {brief ? <Brief memo={memo} link /> : null}
      {action}
    </div>
  );
}

/** Содержимое вкладки «Оплата» для служебки: записка, счёт поставщика и форма «Оплачено». */
export function MemoPanel({
  memoId,
  brief = false,
  variant = "panel",
  onDone,
}: {
  memoId: string;
  brief?: boolean;
  variant?: "panel" | "sheet";
  onDone?: (() => void) | undefined;
}) {
  const query = useGetPaymentMemo(memoId);
  const labels = useStateLabels();
  return (
    <QueryState query={query} labels={labels} level={3} compact>
      {(memo) => <Body memo={memo} variant={variant} brief={brief} onDone={onDone} />}
    </QueryState>
  );
}

function SheetTitle({ memoId }: { memoId: string }) {
  const { t } = useTranslation("payments");
  const query = useGetPaymentMemo(memoId);
  return (
    <>
      {query.data
        ? t("memo.panel.sheetTitle", { number: query.data.number ?? query.data.subject })
        : t("memo.panel.sheetLabel")}
    </>
  );
}

export function MemoSlot({ memoId, brief = false }: { memoId: string; brief?: boolean }) {
  const { t } = useTranslation("payments");
  return (
    <DecisionSlot
      tab="payment"
      sheet="payment"
      title={<SheetTitle memoId={memoId} />}
      label={t("memo.panel.sheetLabel")}
      closeLabel={t("panel.sheetClose")}
    >
      {(variant, onDone) => (
        <MemoPanel memoId={memoId} brief={brief} variant={variant} onDone={onDone} />
      )}
    </DecisionSlot>
  );
}
