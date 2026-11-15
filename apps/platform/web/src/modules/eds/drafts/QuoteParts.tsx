import { useTranslation } from "react-i18next";

import type { QuoteApprovalCard } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { DataTable } from "../../../shared/ui/DataTable/DataTable";
import { LockIcon } from "../../../shared/ui/icons";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { Restricted } from "../decision/Restricted";

type QuoteLine = NonNullable<QuoteApprovalCard["lines"]>[number];

/** Состав КП из ERP: № · наименование · кол-во · цена · сумма · срок; итоги без НДС / НДС / с НДС (SPEC-v3 §7.3). */
export function QuoteLines({ quote }: { quote: QuoteApprovalCard }) {
  const { t } = useTranslation("quotes");
  const currency = quote.totals?.currency;
  const money = (value: string) => <MoneyText value={value} currency={currency} />;
  if (quote.lines === null) {
    return (
      <>
        <p className="pf-hint">{t("card.noLines")}</p>
        <SnapshotTotal quote={quote} />
      </>
    );
  }
  if (quote.lines.length === 0) return <p className="pf-hint">{t("card.emptyLines")}</p>;
  return (
    <>
      <DataTable<QuoteLine>
        tableId="eds.quote.lines"
        caption={t("card.lines")}
        scrollLabel={t("card.linesScroll")}
        className="pf-dec-table pf-dec-lines"
        rows={quote.lines}
        rowKey={(line) => String(line.position)}
        toolsTarget={null}
        columns={[
          {
            id: "position",
            header: t("card.columns.position"),
            width: 56,
            cellClassName: "pf-num",
            cell: (line) => line.position,
          },
          {
            id: "name",
            header: t("card.columns.name"),
            width: null,
            cell: (line) => (
              <>
                {line.name}
                {line.optional ? (
                  <span className="pf-dec-optional"> · {t("card.optional")}</span>
                ) : null}
              </>
            ),
          },
          {
            id: "quantity",
            header: t("card.columns.quantity"),
            width: 110,
            numeric: true,
            cell: (line) => `${String(line.quantity)}${line.unit ? ` ${line.unit}` : ""}`,
          },
          {
            id: "price",
            header: t("card.columns.price"),
            width: 150,
            numeric: true,
            cell: (line) => money(line.unit_price),
          },
          {
            id: "amount",
            header: t("card.columns.amount"),
            width: 150,
            numeric: true,
            cell: (line) => money(line.amount),
          },
          {
            id: "term",
            header: t("card.columns.term"),
            width: 110,
            numeric: true,
            cell: (line) =>
              line.lead_time_days !== null ? t("card.days", { count: line.lead_time_days }) : "—",
          },
        ]}
      />
      {quote.totals ? (
        <div className="pf-table-totals">
          <Totals quote={quote} />
        </div>
      ) : null}
      <Mismatch quote={quote} />
    </>
  );
}

/** Итог из снимка КП в EDS — когда строк и итогов ERP нет (ERP не ответил, нет доступа, другая редакция КП). */
function SnapshotTotal({ quote }: { quote: QuoteApprovalCard }) {
  const { t } = useTranslation("quotes");
  const total = quote.snapshot_total;
  if (!total) return null;
  return (
    <DefinitionList
      items={[
        {
          label: t("card.snapshotTotal"),
          value: <MoneyText value={total.amount} strong currency={total.currency} />,
        },
      ]}
    />
  );
}

/** Итог ERP расходится со снимком EDS: КП менялось после передачи на одобрение — предупреждение у итогов. */
function Mismatch({ quote }: { quote: QuoteApprovalCard }) {
  const { t } = useTranslation("quotes");
  const format = useFormat();
  if (!quote.totals_mismatch || !quote.totals || !quote.snapshot_total) return null;
  const money = (value: string, currency: string) => format.money(value, { currency });
  return (
    <p className="pf-dec-warn" role="note">
      {t("card.mismatch", {
        erp: money(quote.totals.total, quote.totals.currency),
        snapshot: money(quote.snapshot_total.amount, quote.snapshot_total.currency),
      })}
    </p>
  );
}

function Totals({ quote }: { quote: QuoteApprovalCard }) {
  const { t } = useTranslation("quotes");
  const totals = quote.totals;
  if (!totals) return null;
  const currency = totals.currency;
  const money = (value: string | null) =>
    value === null ? null : <MoneyText value={value} currency={currency} />;
  return (
    <DefinitionList
      items={[
        { label: t("card.totals.subtotal"), value: money(totals.subtotal) },
        {
          label: totals.vat_rate
            ? t("card.totals.vatRate", { rate: totals.vat_rate })
            : t("card.totals.vat"),
          value: money(totals.vat_amount),
        },
        {
          label: t("card.totals.total"),
          value: <MoneyText value={totals.total} strong currency={currency} />,
        },
      ]}
    />
  );
}

/** Внутренний блок КП: только роль с группой `cost_margin`; клиент получит PDF без этих полей. */
export function InternalBlock({ quote }: { quote: QuoteApprovalCard }) {
  const { t } = useTranslation("quotes");
  const { date } = useFormat();
  const internal = quote.internal;
  if (!internal) return null;
  const currency = quote.totals?.currency;
  return (
    <Restricted group="cost_margin">
      <section className="pf-dec-internal" aria-labelledby="pf-dec-internal-title">
        <h2 className="pf-dec-internal-title" id="pf-dec-internal-title">
          <LockIcon size={14} />
          {t("card.internal.title")}
        </h2>
        <DefinitionList
          items={[
            {
              label: t("card.internal.cost"),
              value: internal.cost ? <MoneyText value={internal.cost} currency={currency} /> : null,
            },
            {
              label: t("card.internal.margin"),
              value: (
                <>
                  {internal.margin_pct} %
                  {internal.margin_amount ? (
                    <>
                      {" · "}
                      <MoneyText value={internal.margin_amount} currency={currency} />
                    </>
                  ) : null}
                </>
              ),
            },
            {
              label: t("card.internal.minMargin"),
              value: internal.min_margin_pct ? `${internal.min_margin_pct} %` : null,
            },
            { label: t("card.internal.paymentTerms"), value: internal.payment_terms },
            {
              label: t("card.internal.validUntil"),
              value: internal.valid_until ? date(internal.valid_until) : null,
            },
            {
              label: t("card.internal.supplierUntil"),
              value: internal.supplier_price_until ? date(internal.supplier_price_until) : null,
            },
          ]}
        />
        <p className="pf-hint">{t("card.internal.note")}</p>
      </section>
    </Restricted>
  );
}
