import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import type { PaymentRow } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { DataTable, type DataColumn } from "../../../shared/ui/DataTable/DataTable";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { withParams } from "../inbox/api";
import { InvoiceStatus } from "./InvoiceStatus";
import { invoicePath, moneyProps, rowAction } from "./model";

/** Ширины колонок: номер и проект, клиент (гибкая), сумма, выставлен, срок, статус, действие (UX-1c, S9) */
const COLS = {
  number: 140,
  amount: 150,
  issued: 110,
  due: 140,
  status: 170,
  action: 140,
};

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
  // Ширины по типу (COLS, T1); остальное — настройка сотрудника в «Столбцах» (пункт «Т»).
  const columns: DataColumn<PaymentRow>[] = [
    {
      id: "number",
      header: t("list.columns.number"),
      width: COLS.number,
      cellClassName: "pf-num",
      cell: (row) => (
        <>
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
        </>
      ),
    },
    {
      id: "client",
      header: t("list.columns.client"),
      width: null,
      cellClassName: "pf-ell",
      cellTitle: (row) => row.client_name,
      cell: (row) => row.client_name,
    },
    {
      id: "amount",
      header: t("list.columns.amount"),
      width: COLS.amount,
      numeric: true,
      cell: (row) => (
        <>
          <Amount row={row} />
        </>
      ),
    },
    {
      id: "issued",
      header: t("list.columns.issued"),
      width: COLS.issued,
      cellClassName: "pf-num",
      cell: (row) => (row.issued_at ? date(row.issued_at) : "—"),
    },
    {
      id: "due",
      header: t("list.columns.due"),
      width: COLS.due,
      cellClassName: "pf-num",
      cell: (row) => (
        <>
          <Due row={row} />
        </>
      ),
    },
    {
      id: "status",
      header: t("list.columns.status"),
      width: COLS.status,
      cell: (row) => (
        <>
          <InvoiceStatus status={row.status} />
        </>
      ),
    },
    {
      id: "action",
      header: t("list.columns.action"),
      headerHidden: true,
      width: COLS.action,
      cell: (row) => (
        <>
          <ActionButton row={row} />
        </>
      ),
    },
  ];
  return (
    <DataTable
      tableId="eds.payments"
      caption={t("list.caption")}
      scrollLabel={t("list.scroll")}
      className="pf-dec-table pf-pay-table"
      flexMin={200}
      columns={columns}
      rows={items}
      rowKey={(row) => String(row.id)}
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
