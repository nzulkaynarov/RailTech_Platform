import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import type { PaymentRow } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { TableCols } from "../../../shared/ui/DataBlock";
import { tableMinWidth } from "../../../shared/ui/tableWidth";
import { ScrollRegion } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { withParams } from "../inbox/api";
import { InvoiceStatus } from "./InvoiceStatus";
import { invoicePath, moneyProps, rowAction } from "./model";

/** Ширины колонок: номер и проект, клиент (гибкая), сумма, выставлен, срок, статус, действие (UX-1c, S9) */
const COLS = [140, null, 150, 110, 140, 170, 140] as const;

function useSelect() {
  const [params] = useSearchParams();
  const { mobile } = useViewport();
  // Строка открывает счёт в боковом окне без перехода; на телефоне — лист на весь экран.
  return (row: PaymentRow) =>
    withParams(params, {
      payment: String(row.id),
      memo: null,
      tab: "payment",
      panel: mobile ? null : "open",
      sheet: mobile ? "payment" : null,
    });
}

function Due({ row }: { row: PaymentRow }) {
  const { t } = useTranslation("payments");
  const { date } = useFormat();
  if (!row.due_date) return <>—</>;
  return (
    <>
      {date(row.due_date)}
      {row.days_overdue ? (
        <div className="pf-hint pf-pay-overdue">
          {t("list.overdueDays", { count: row.days_overdue })}
        </div>
      ) : null}
    </>
  );
}

function Amount({ row }: { row: PaymentRow }) {
  const { t } = useTranslation("payments");
  const { money } = useFormat();
  const partial = row.status === "partially_paid";
  return (
    <>
      <MoneyText {...moneyProps(row.amount)} />
      {partial ? (
        <div className="pf-hint">
          {t("list.balance", {
            amount: money(row.balance.amount, { currency: row.balance.currency }),
          })}
        </div>
      ) : null}
    </>
  );
}

function ActionButton({ row }: { row: PaymentRow }) {
  const { t } = useTranslation("payments");
  const { me } = useAuth();
  // Роль с чтением (директор, менеджер) счёт только открывает: оплату подтверждает бухгалтер.
  const action = me.resources["eds.payments"] === "full" ? rowAction(row) : "open";
  return (
    <LinkButton
      size="small"
      to={invoicePath(row.id)}
      aria-label={t("list.actionLabel", {
        action: t(`list.actionName.${action}`),
        number: row.number,
      })}
    >
      {t(`list.action.${action}`)}
    </LinkButton>
  );
}

/** Таблица счетов (SPEC-v3 §7.3): счёт · проект · клиент · сумма · выставлен · срок · статус · действие; на телефоне — карточки. */
export function InvoiceRows({
  items,
  selected,
}: {
  items: readonly PaymentRow[];
  selected: string | null;
}) {
  const { t } = useTranslation("payments");
  const { date } = useFormat();
  const { mobile } = useViewport();
  const select = useSelect();
  const navigate = useNavigate();
  const isSelected = (row: PaymentRow) => selected === String(row.id);

  if (mobile) {
    return (
      <ul className="pf-dec-cards" aria-label={t("list.caption")}>
        {items.map((row) => (
          <li key={row.id} data-selected={isSelected(row)}>
            <div className="pf-dec-card-head">
              <Link
                className="pf-focusable pf-dec-number"
                to={select(row)}
                aria-label={t("list.select", { number: row.number })}
              >
                {row.number}
              </Link>
              <InvoiceStatus status={row.status} />
            </div>
            <p className="pf-dec-card-subject">{row.client_name}</p>
            <p className="pf-hint">
              {row.project_number} · <Amount row={row} />
            </p>
            <div className="pf-dec-card-foot">
              <span className="pf-hint">
                <Due row={row} />
              </span>
              <ActionButton row={row} />
            </div>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <ScrollRegion label={t("list.scroll")}>
      <table
        className="pf-dec-table pf-pay-table pf-fixed-table"
        style={{ minWidth: tableMinWidth(COLS, 200) }}
      >
        <caption className="pf-sr-only">{t("list.caption")}</caption>
        <TableCols widths={COLS} />
        <thead>
          <tr>
            <th scope="col">{t("list.columns.number")}</th>
            <th scope="col">{t("list.columns.client")}</th>
            <th scope="col" className="pf-dec-right">
              {t("list.columns.amount")}
            </th>
            <th scope="col">{t("list.columns.issued")}</th>
            <th scope="col">{t("list.columns.due")}</th>
            <th scope="col">{t("list.columns.status")}</th>
            <th scope="col">
              <span className="pf-sr-only">{t("list.columns.action")}</span>
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
                  aria-label={t("list.select", { number: row.number })}
                  aria-current={isSelected(row) ? "true" : undefined}
                >
                  {row.number}
                </Link>
                <div className="pf-hint">{row.project_number}</div>
              </td>
              <td className="pf-ell" title={row.client_name}>
                {row.client_name}
              </td>
              <td className="pf-dec-right">
                <Amount row={row} />
              </td>
              <td className="pf-num">{row.issued_at ? date(row.issued_at) : "—"}</td>
              <td className="pf-num">
                <Due row={row} />
              </td>
              <td>
                <InvoiceStatus status={row.status} />
              </td>
              <td>
                <ActionButton row={row} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}
