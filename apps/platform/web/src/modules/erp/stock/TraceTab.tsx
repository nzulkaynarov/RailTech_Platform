import { Card, Input } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import type { StockTraceUnit } from "../../../shared/api/generated/model";
import { useSearchStockTrace } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { useStateLabels } from "./api";

/**
 * «Склад · Прослеживаемость» (ADR-0021, L0-3): поиск по серийному номеру или партии — откуда единица (приёмка, заказ
 * поставщику, поставщик, изготовитель, документ соответствия) и куда ушла (отгрузка, клиент, проект). Номер — в адресе
 * (`?q=`), чтобы ссылку можно было переслать. Эталоны: Business Central «Item Tracing», Odoo «Traceability» у партии.
 */
export function TraceTab() {
  const { t } = useTranslation("stock");
  const labels = useStateLabels();
  const [params, setParams] = useSearchParams();
  const query = (params.get("q") ?? "").trim();
  const [input, setInput] = useState(query);
  const result = useSearchStockTrace({ q: query }, { query: { enabled: query.length >= 2 } });
  return (
    <div className="pf-calc-stack">
      <Card size="small" title={<h2 className="pf-calc-title">{t("trace.title")}</h2>}>
        <Input.Search
          aria-label={t("trace.search")}
          placeholder={t("trace.searchPlaceholder")}
          enterButton={t("trace.find")}
          className="pf-stock-search"
          value={input}
          maxLength={100}
          onChange={(event) => {
            setInput(event.target.value);
          }}
          onSearch={(value) => {
            setParams(
              (prev) => {
                const next = new URLSearchParams(prev);
                const text = value.trim();
                if (text) next.set("q", text);
                else next.delete("q");
                return next;
              },
              { replace: true },
            );
          }}
        />
        {query.length < 2 ? <p className="pf-hint">{t("trace.hint")}</p> : null}
      </Card>
      {query.length >= 2 ? (
        <QueryState query={result} labels={labels} level={3}>
          {(data) =>
            data.items.length === 0 ? (
              <EmptyState title={t("trace.empty.title")} text={t("trace.empty.text", { query })} />
            ) : (
              <ul className="pf-stock-trace-results" aria-label={t("trace.results")}>
                {data.items.map((unit) => (
                  <li key={unit.id}>
                    <UnitCard unit={unit} />
                  </li>
                ))}
              </ul>
            )
          }
        </QueryState>
      ) : null}
    </div>
  );
}

function UnitCard({ unit }: { unit: StockTraceUnit }) {
  const { t } = useTranslation("stock");
  const { date, activity } = useFormat();
  const o = unit.origin;
  return (
    <Card
      size="small"
      title={
        <h3 className="pf-calc-title">
          {t(`trace.kind.${unit.kind}`)} <span className="pf-num">{unit.number}</span>
        </h3>
      }
      extra={
        unit.status === "shipped" ? (
          <StatusTag tone="default">{t("trace.status.shipped")}</StatusTag>
        ) : (
          <StatusTag tone="green">{t("trace.status.in_stock")}</StatusTag>
        )
      }
    >
      <p>
        {unit.product.name}
        {unit.product.article ? (
          <span className="pf-hint pf-num"> · {unit.product.article}</span>
        ) : null}
        {unit.kind === "lot" ? (
          <span className="pf-hint">
            {" "}
            · {t("trace.lotShipped", { shipped: unit.shipped_quantity, total: unit.quantity })}
          </span>
        ) : null}
      </p>
      <div className="pf-stock-trace-way">
        <section aria-label={t("trace.from")}>
          <h4 className="pf-dec-subhead">{t("trace.from")}</h4>
          <DefinitionList
            items={[
              { label: t("trace.manufacturer"), value: o.manufacturer },
              { label: t("trace.supplier"), value: o.supplier },
              {
                label: t("trace.order"),
                value: (
                  <Link className="pf-focusable pf-num" to={o.order_path}>
                    {o.order_number}
                  </Link>
                ),
              },
              {
                label: t("trace.received"),
                value: `${activity(o.received_at)}${o.supplier_doc ? ` · ${t("receipts.doc", { doc: o.supplier_doc })}` : ""}`,
              },
              {
                label: t("trace.document"),
                value: o.doc_number
                  ? `${o.doc_number}${o.doc_valid_until ? ` · ${t("trace.until", { date: date(o.doc_valid_until) })}` : ""}`
                  : null,
              },
              {
                label: t("trace.expiryLabel"),
                value: unit.expiry_date ? date(unit.expiry_date) : null,
              },
              {
                label: t("trace.orderedFor"),
                value: o.request ? (
                  <Link className="pf-focusable" to={o.request.path}>
                    {o.request.number}
                  </Link>
                ) : null,
              },
            ]}
          />
        </section>
        <section aria-label={t("trace.to")}>
          <h4 className="pf-dec-subhead">{t("trace.to")}</h4>
          {unit.destinations.length === 0 ? (
            <p className="pf-hint">{t("trace.notShipped")}</p>
          ) : (
            <ul className="pf-stock-list">
              {unit.destinations.map((d) => (
                <li key={`${d.shipment_number}:${String(d.quantity)}`}>
                  <span>
                    <span className="pf-num">{d.shipment_number}</span> ·{" "}
                    <Link className="pf-focusable" to={d.request.path}>
                      {d.request.number}
                    </Link>
                    {d.request.client ? (
                      <span className="pf-hint"> · {d.request.client}</span>
                    ) : null}
                  </span>
                  <span className="pf-hint">
                    {activity(d.shipped_at)}
                    {unit.kind === "lot" ? ` · ${String(d.quantity)}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </Card>
  );
}
