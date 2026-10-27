import { useTranslation } from "react-i18next";

import type { QuoteApprovalCard } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { ScrollRegion } from "../../../shared/ui/FormParts";
import { LockIcon } from "../../../shared/ui/icons";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { Restricted } from "../decision/Restricted";

/** Состав КП из ERP: № · наименование · кол-во · цена · сумма · срок; итоги без НДС / НДС / с НДС (SPEC-v3 §7.3). */
export function QuoteLines({ quote }: { quote: QuoteApprovalCard }) {
  const { t } = useTranslation("quotes");
  const currency = quote.totals?.currency;
  const money = (value: string) => (
    <MoneyText value={value} {...(currency && currency !== "UZS" ? { currency } : {})} />
  );
  if (quote.lines === null) return <p className="pf-hint">{t("card.noLines")}</p>;
  if (quote.lines.length === 0) return <p className="pf-hint">{t("card.emptyLines")}</p>;
  return (
    <>
      <ScrollRegion label={t("card.linesScroll")}>
        <table className="pf-dec-table pf-dec-lines">
          <caption className="pf-sr-only">{t("card.lines")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("card.columns.position")}</th>
              <th scope="col">{t("card.columns.name")}</th>
              <th scope="col" className="pf-dec-right">
                {t("card.columns.quantity")}
              </th>
              <th scope="col" className="pf-dec-right">
                {t("card.columns.price")}
              </th>
              <th scope="col" className="pf-dec-right">
                {t("card.columns.amount")}
              </th>
              <th scope="col" className="pf-dec-right">
                {t("card.columns.term")}
              </th>
            </tr>
          </thead>
          <tbody>
            {quote.lines.map((line) => (
              <tr key={line.position}>
                <td className="pf-num">{line.position}</td>
                <td>
                  {line.name}
                  {line.optional ? (
                    <span className="pf-dec-optional"> · {t("card.optional")}</span>
                  ) : null}
                </td>
                <td className="pf-num pf-dec-right">
                  {line.quantity}
                  {line.unit ? ` ${line.unit}` : ""}
                </td>
                <td className="pf-dec-right">{money(line.unit_price)}</td>
                <td className="pf-dec-right">{money(line.amount)}</td>
                <td className="pf-num pf-dec-right">
                  {line.lead_time_days !== null
                    ? t("card.days", { count: line.lead_time_days })
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollRegion>
      {quote.totals ? <Totals quote={quote} /> : null}
    </>
  );
}

function Totals({ quote }: { quote: QuoteApprovalCard }) {
  const { t } = useTranslation("quotes");
  const totals = quote.totals;
  if (!totals) return null;
  const currency = totals.currency === "UZS" ? {} : { currency: totals.currency };
  const money = (value: string | null) =>
    value === null ? null : <MoneyText value={value} {...currency} />;
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
          value: <MoneyText value={totals.total} strong {...currency} />,
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
  const currency = quote.totals?.currency ?? "UZS";
  const opts = currency === "UZS" ? {} : { currency };
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
              value: internal.cost ? <MoneyText value={internal.cost} {...opts} /> : null,
            },
            {
              label: t("card.internal.margin"),
              value: (
                <>
                  {internal.margin_pct} %
                  {internal.margin_amount ? (
                    <>
                      {" · "}
                      <MoneyText value={internal.margin_amount} {...opts} />
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
