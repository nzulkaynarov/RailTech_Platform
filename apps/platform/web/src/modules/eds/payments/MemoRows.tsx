import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useViewport } from "../../../app/shell/useViewport";
import type { PaymentMemoRow } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { DataTable, type DataColumn } from "../../../shared/ui/DataTable/DataTable";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { withParams } from "../inbox/api";
import { memoPath, moneyProps } from "./model";

/** Ширины колонок: номер и тема (гибкая), автор, сумма, срок, счёт, статус, действие (UX-1c, S9) */
const COLS = {
  author: 170,
  amount: 150,
  due: 110,
  invoice: 140,
  status: 170,
  action: 140,
};

function useSelect() {
  const [params] = useSearchParams();
  const { mobile } = useViewport();
  return (row: PaymentMemoRow) =>
    withParams(params, {
      memo: row.id,
      payment: null,
      tab: "payment",
      panel: mobile ? null : "open",
      sheet: mobile ? "payment" : null,
    });
}

function Status({ row }: { row: PaymentMemoRow }) {
  const { t } = useTranslation("payments");
  const { date } = useFormat();
  return (
    <StatusTag kind="memo" status={row.status}>
      {t(`memo.status.${row.status}`)}
      {row.paid_on ? ` · ${t("memo.paidOn", { date: date(row.paid_on) })}` : ""}
    </StatusTag>
  );
}

function InvoiceMark({ row }: { row: PaymentMemoRow }) {
  const { t } = useTranslation("payments");
  return row.invoice_attached ? (
    <>{t("memo.invoice.attached")}</>
  ) : (
    <span className="pf-pay-overdue">{t("memo.invoice.missing")}</span>
  );
}

/** Таблица служебок к оплате: служебка · тема · от кого · сумма · нужно до · счёт поставщика · статус · действие. */
export function MemoRows({
  items,
  selected,
}: {
  items: readonly PaymentMemoRow[];
  selected: string | null;
}) {
  const { t } = useTranslation("payments");
  const { date } = useFormat();
  const { mobile } = useViewport();
  const select = useSelect();
  const navigate = useNavigate();
  const label = (row: PaymentMemoRow) => row.number ?? row.subject;
  const isSelected = (row: PaymentMemoRow) => selected === row.id;
  const open = (row: PaymentMemoRow) => (
    <LinkButton
      size="small"
      to={memoPath(row.id)}
      aria-label={t("memo.openLabel", { number: label(row) })}
    >
      {t("list.open")}
    </LinkButton>
  );

  if (mobile) {
    return (
      <ul className="pf-dec-cards" aria-label={t("memo.caption")}>
        {items.map((row) => (
          <li key={row.id} data-selected={isSelected(row)}>
            <div className="pf-dec-card-head">
              <Link
                className="pf-focusable pf-dec-number"
                to={select(row)}
                aria-label={t("memo.select", { number: label(row) })}
              >
                {label(row)}
              </Link>
              <Status row={row} />
            </div>
            <p className="pf-dec-card-subject">{row.subject}</p>
            <p className="pf-hint">
              {row.author.full_name}
              {row.amount ? (
                <>
                  {" · "}
                  <MoneyText {...moneyProps(row.amount)} />
                </>
              ) : null}
            </p>
            <div className="pf-dec-card-foot">
              <span className="pf-hint">
                {t("memo.columns.invoice")}: <InvoiceMark row={row} />
              </span>
              {open(row)}
            </div>
          </li>
        ))}
      </ul>
    );
  }
  // Ширины по типу (COLS, T1); остальное — настройка сотрудника в «Столбцах» (пункт «Т»).
  const columns: DataColumn<PaymentMemoRow>[] = [
    {
      id: "number",
      header: t("memo.columns.number"),
      width: null,
      cellClassName: "pf-num",
      cell: (row) => (
        <>
          <Link
            className="pf-focusable pf-dec-number"
            to={select(row)}
            replace
            aria-label={t("memo.select", { number: label(row) })}
            aria-current={isSelected(row) ? "true" : undefined}
          >
            {label(row)}
          </Link>
          <div className="pf-hint">{row.subject}</div>
        </>
      ),
    },
    {
      id: "author",
      header: t("memo.columns.author"),
      width: COLS.author,
      cellClassName: "pf-ell",
      cellTitle: (row) => row.author.full_name,
      cell: (row) => row.author.full_name,
    },
    {
      id: "amount",
      header: t("memo.columns.amount"),
      width: COLS.amount,
      numeric: true,
      cell: (row) => <>{row.amount ? <MoneyText {...moneyProps(row.amount)} /> : "—"}</>,
    },
    {
      id: "due",
      header: t("memo.columns.due"),
      width: COLS.due,
      cellClassName: "pf-num",
      cell: (row) => (row.due_date ? date(row.due_date) : "—"),
    },
    {
      id: "invoice",
      header: t("memo.columns.invoice"),
      width: COLS.invoice,
      cell: (row) => (
        <>
          <InvoiceMark row={row} />
        </>
      ),
    },
    {
      id: "status",
      header: t("memo.columns.status"),
      width: COLS.status,
      cell: (row) => (
        <>
          <Status row={row} />
        </>
      ),
    },
    {
      id: "action",
      header: t("memo.columns.action"),
      headerHidden: true,
      width: COLS.action,
      cell: (row) => open(row),
    },
  ];
  return (
    <DataTable
      tableId="eds.payments.memos"
      caption={t("memo.caption")}
      scrollLabel={t("memo.scroll")}
      className="pf-dec-table pf-pay-table"
      flexMin={200}
      columns={columns}
      rows={items}
      rowKey={(row) => row.id}
      rowAttrs={(row) => ({
        "data-selected": isSelected(row),
        onClick: (event) => {
          if ((event.target as HTMLElement).closest("a,button")) return;
          void navigate(select(row), { replace: true });
        },
      })}
    />
  );
}
