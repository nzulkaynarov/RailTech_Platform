import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useViewport } from "../../../app/shell/useViewport";
import type { PaymentMemoRow } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { TableCols } from "../../../shared/ui/DataBlock";
import { tableMinWidth } from "../../../shared/ui/tableWidth";
import { ScrollRegion } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { withParams } from "../inbox/api";
import { memoPath, moneyProps } from "./model";

/** Ширины колонок: номер и тема (гибкая), автор, сумма, срок, счёт, статус, действие (UX-1c, S9) */
const COLS = [null, 170, 150, 110, 140, 170, 140] as const;

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
    <StatusTag tone={row.status === "paid" ? "green" : "blue"}>
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
  return (
    <ScrollRegion label={t("memo.scroll")}>
      <table
        className="pf-dec-table pf-pay-table pf-fixed-table"
        style={{ minWidth: tableMinWidth(COLS, 200) }}
      >
        <caption className="pf-sr-only">{t("memo.caption")}</caption>
        <TableCols widths={COLS} />
        <thead>
          <tr>
            <th scope="col">{t("memo.columns.number")}</th>
            <th scope="col">{t("memo.columns.author")}</th>
            <th scope="col" className="pf-dec-right">
              {t("memo.columns.amount")}
            </th>
            <th scope="col">{t("memo.columns.due")}</th>
            <th scope="col">{t("memo.columns.invoice")}</th>
            <th scope="col">{t("memo.columns.status")}</th>
            <th scope="col">
              <span className="pf-sr-only">{t("memo.columns.action")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <tr
              key={row.id}
              data-row
              data-selected={isSelected(row)}
              onClick={(event) => {
                if ((event.target as HTMLElement).closest("a,button")) return;
                void navigate(select(row), { replace: true });
              }}
            >
              <td className="pf-num">
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
              </td>
              <td className="pf-ell" title={row.author.full_name}>
                {row.author.full_name}
              </td>
              <td className="pf-dec-right">
                {row.amount ? <MoneyText {...moneyProps(row.amount)} /> : "—"}
              </td>
              <td className="pf-num">{row.due_date ? date(row.due_date) : "—"}</td>
              <td>
                <InvoiceMark row={row} />
              </td>
              <td>
                <Status row={row} />
              </td>
              <td>{open(row)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}
