import { App, Button, Card, Input, InputNumber } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { useViewport } from "../../../app/shell/useViewport";
import type { StockReservation, StockShipment } from "../../../shared/api/generated/model";
import {
  useListStockReservations,
  useListStockShipments,
  useShipFromStock,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { Consequence } from "../../../shared/ui/Consequence";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { ErrorNote, QueryState, ScrollRegion } from "../../../shared/ui/FormParts";
import { clean, useErrorText, useRefreshStock, useStateLabels } from "./api";

function NewShipment({ manage }: { manage: boolean }) {
  const { t } = useTranslation("stock");
  const { message } = App.useApp();
  const refresh = useRefreshStock();
  const errorText = useErrorText();
  const [input, setInput] = useState("");
  const [request, setRequest] = useState<string | null>(null);
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [tracking, setTracking] = useState("");
  const [carrier, setCarrier] = useState("");
  const [error, setError] = useState<string | null>(null);
  const reservations = useListStockReservations(request ? { request } : undefined, {
    query: { enabled: request !== null },
  });
  const ship = useShipFromStock({
    mutation: {
      onSuccess: (shipment) => {
        setError(null);
        refresh();
        setQuantities({});
        setTracking("");
        setCarrier("");
        void message.success(t("shipments.done", { number: shipment.number }));
      },
      onError: (e) => {
        setError(errorText(e));
      },
    },
  });
  const labels = useStateLabels();
  const rows: StockReservation[] = reservations.data?.items ?? [];
  const qtyOf = (r: StockReservation) => quantities[r.id] ?? r.remaining;
  const picked = rows.filter((r) => qtyOf(r) > 0);
  return (
    <Card size="small" title={<h2 className="pf-calc-title">{t("shipments.newTitle")}</h2>}>
      <div className="pf-calc-stack">
        <Input.Search
          aria-label={t("shipments.request")}
          placeholder={t("shipments.requestPlaceholder")}
          enterButton={t("shipments.find")}
          value={input}
          maxLength={40}
          onChange={(event) => {
            setInput(event.target.value);
          }}
          onSearch={(value) => {
            const number = value.trim();
            setError(null);
            setQuantities({});
            setRequest(number === "" ? null : number);
          }}
        />
        {request === null ? (
          <p className="pf-hint">{t("shipments.hint")}</p>
        ) : (
          <QueryState query={reservations} labels={labels} level={3}>
            {() =>
              rows.length === 0 ? (
                <EmptyState
                  title={t("shipments.noReservations.title")}
                  text={t("shipments.noReservations.text", { request })}
                />
              ) : (
                <>
                  <ul className="pf-stock-receive">
                    {rows.map((r) => (
                      <li key={r.id}>
                        <div>
                          <strong>{r.product_name}</strong>
                          <div className="pf-hint">
                            {t("shipments.reserved", { remaining: r.remaining, total: r.quantity })}
                          </div>
                        </div>
                        <InputNumber
                          min={0}
                          max={r.remaining}
                          precision={0}
                          value={qtyOf(r)}
                          disabled={!manage}
                          aria-label={t("shipments.quantityLabel", { name: r.product_name })}
                          onChange={(value) => {
                            setQuantities((prev) => ({ ...prev, [r.id]: value ?? 0 }));
                          }}
                        />
                      </li>
                    ))}
                  </ul>
                  <div className="pf-calc-add-row">
                    <label className="pf-calc-crew-field">
                      <span className="pf-hint">{t("shipments.tracking")}</span>
                      <Input
                        value={tracking}
                        maxLength={128}
                        onChange={(event) => {
                          setTracking(event.target.value);
                        }}
                      />
                    </label>
                    <label className="pf-calc-crew-field">
                      <span className="pf-hint">{t("shipments.carrier")}</span>
                      <Input
                        value={carrier}
                        maxLength={128}
                        onChange={(event) => {
                          setCarrier(event.target.value);
                        }}
                      />
                    </label>
                  </div>
                  <ErrorNote message={error} />
                  {manage ? (
                    <>
                      <div>
                        <Button
                          type="primary"
                          loading={ship.isPending}
                          disabled={picked.length === 0}
                          onClick={() => {
                            ship.mutate({
                              data: {
                                request,
                                lines: picked.map((r) => ({
                                  reservation_id: r.id,
                                  quantity: qtyOf(r),
                                })),
                                ...(clean(tracking) ? { tracking: clean(tracking) } : {}),
                                ...(clean(carrier) ? { carrier: clean(carrier) } : {}),
                              },
                            });
                          }}
                        >
                          {t("shipments.submit")}
                        </Button>
                      </div>
                      <Consequence
                        items={t("shipments.consequence", { returnObjects: true }) as string[]}
                      />
                    </>
                  ) : (
                    <p className="pf-hint">{t("shipments.readOnly")}</p>
                  )}
                </>
              )
            }
          </QueryState>
        )}
      </div>
    </Card>
  );
}

function Rows({ items }: { items: readonly StockShipment[] }) {
  const { t } = useTranslation("stock");
  const { activity } = useFormat();
  const { mobile } = useViewport();
  if (mobile) {
    return (
      <ul className="pf-calc-cards" aria-label={t("shipments.caption")}>
        {items.map((s) => (
          <li key={s.id}>
            <div className="pf-calc-card-head">
              <span className="pf-num pf-calc-number">{s.number}</span>
              <Link className="pf-focusable" to={s.request.path}>
                {s.request.number}
              </Link>
            </div>
            <p className="pf-hint">
              {s.lines.map((l) => `${l.name} · ${String(l.quantity)}`).join("; ")}
            </p>
            <p className="pf-hint">
              {[s.tracking, s.carrier, activity(s.shipped_at)].filter(Boolean).join(" · ")}
            </p>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <ScrollRegion label={t("shipments.scroll")}>
      <table className="pf-calc-table">
        <caption className="pf-sr-only">{t("shipments.caption")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("shipments.columns.number")}</th>
            <th scope="col">{t("shipments.columns.request")}</th>
            <th scope="col">{t("shipments.columns.lines")}</th>
            <th scope="col">{t("shipments.columns.tracking")}</th>
            <th scope="col">{t("shipments.columns.when")}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((s) => (
            <tr key={s.id}>
              <td className="pf-num">{s.number}</td>
              <td>
                <Link className="pf-focusable" to={s.request.path}>
                  {s.request.number}
                </Link>
                <div className="pf-hint">{s.request.client ?? "—"}</div>
              </td>
              <td>
                {s.lines.map((l, index) => (
                  <div key={index}>
                    {l.name} · <span className="pf-num">{l.quantity}</span>
                    {l.cell ? <span className="pf-hint"> ({l.cell})</span> : null}
                  </div>
                ))}
              </td>
              <td>
                {s.tracking ?? "—"}
                {s.carrier ? <div className="pf-hint">{s.carrier}</div> : null}
              </td>
              <td>
                {activity(s.shipped_at)}
                {s.shipped_by ? <div className="pf-hint">{s.shipped_by}</div> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}

/** Вкладка «Отгрузки»: отгрузка по проекту (резервы заявки → накладная ОТГ, трек) и журнал отгрузок. */
export function ShipmentsTab() {
  const { t } = useTranslation("stock");
  const labels = useStateLabels();
  const query = useListStockShipments();
  return (
    <div className="pf-calc-stack">
      <NewShipment manage={query.data?.rights.ship ?? false} />
      <Card
        size="small"
        title={<h2 className="pf-calc-title">{t("shipments.listTitle")}</h2>}
        styles={{ body: { padding: 0 } }}
      >
        <QueryState query={query} labels={labels} level={3}>
          {(data) =>
            data.items.length === 0 ? (
              <EmptyState title={t("shipments.empty.title")} text={t("shipments.empty.text")} />
            ) : (
              <Rows items={data.items} />
            )
          }
        </QueryState>
      </Card>
    </div>
  );
}
