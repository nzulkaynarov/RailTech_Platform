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
import { DataTable, type DataColumn } from "../../../shared/ui/DataTable/DataTable";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { ErrorNote, QueryState } from "../../../shared/ui/FormParts";
import { clean, useErrorText, useRefreshStock, useStateLabels } from "./api";
import { ShipUnits } from "./Tracking";

/** Серийные или партии строки отгрузки: « · SN-1, SN-2» или « · L-7 ×3». */
function unitsText(units: readonly { number: string; quantity: number }[]): string {
  if (units.length === 0) return "";
  return ` · ${units.map((u) => (u.quantity > 1 ? `${u.number} ×${String(u.quantity)}` : u.number)).join(", ")}`;
}

/** Ширины колонок: накладная, заявка, строки (гибкая), трек, когда (UX-1c, S9) */
const COLS = {
  number: 130,
  request: 180,
  tracking: 180,
  when: 170,
};

function NewShipment({ manage }: { manage: boolean }) {
  const { t } = useTranslation("stock");
  const { message } = App.useApp();
  const refresh = useRefreshStock();
  const errorText = useErrorText();
  const [input, setInput] = useState("");
  const [request, setRequest] = useState<string | null>(null);
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  // Серийные и партии по резерву (ADR-0021): единица → сколько из неё.
  const [units, setUnits] = useState<Record<string, Record<string, number>>>({});
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
        setUnits({});
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
  const chosenOf = (r: StockReservation) =>
    Object.values(units[r.id] ?? {}).reduce((sum, n) => sum + n, 0);
  const unpicked = picked.find((r) => r.tracking !== "none" && chosenOf(r) !== qtyOf(r));
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
                        {r.tracking !== "none" && manage && qtyOf(r) > 0 ? (
                          <ShipUnits
                            name={r.product_name}
                            units={r.units}
                            quantity={qtyOf(r)}
                            picked={units[r.id] ?? {}}
                            onChange={(next) => {
                              setUnits((prev) => ({ ...prev, [r.id]: next }));
                            }}
                          />
                        ) : null}
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
                            if (unpicked) {
                              setError(t("trace.problem.units", { name: unpicked.product_name }));
                              return;
                            }
                            ship.mutate({
                              data: {
                                request,
                                lines: picked.map((r) => ({
                                  reservation_id: r.id,
                                  quantity: qtyOf(r),
                                  ...(r.tracking !== "none"
                                    ? {
                                        units: Object.entries(units[r.id] ?? {})
                                          .filter(([, n]) => n > 0)
                                          .map(([unit_id, quantity]) => ({ unit_id, quantity })),
                                      }
                                    : {}),
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
              {s.lines
                .map((l) => `${l.name} · ${String(l.quantity)}${unitsText(l.units)}`)
                .join("; ")}
            </p>
            <p className="pf-hint">
              {[s.tracking, s.carrier, activity(s.shipped_at)].filter(Boolean).join(" · ")}
            </p>
          </li>
        ))}
      </ul>
    );
  }
  // Ширины по типу (COLS, T1); остальное — настройка сотрудника в «Столбцах» (пункт «Т»).
  const columns: DataColumn<StockShipment>[] = [
    {
      id: "number",
      header: t("shipments.columns.number"),
      width: COLS.number,
      cellClassName: "pf-num",
      cell: (s) => s.number,
    },
    {
      id: "request",
      header: t("shipments.columns.request"),
      width: COLS.request,
      cell: (s) => (
        <>
          <Link className="pf-focusable" to={s.request.path}>
            {s.request.number}
          </Link>
          <div className="pf-hint">{s.request.client ?? "—"}</div>
        </>
      ),
    },
    {
      id: "lines",
      header: t("shipments.columns.lines"),
      width: null,
      cell: (s) => (
        <>
          {s.lines.map((l, index) => (
            <div key={index}>
              {l.name} · <span className="pf-num">{l.quantity}</span>
              {l.cell ? <span className="pf-hint"> ({l.cell})</span> : null}
              {l.units.length > 0 ? (
                <div className="pf-hint pf-num">{unitsText(l.units).slice(3)}</div>
              ) : null}
            </div>
          ))}
        </>
      ),
    },
    {
      id: "tracking",
      header: t("shipments.columns.tracking"),
      width: COLS.tracking,
      cell: (s) => (
        <>
          {s.tracking ?? "—"}
          {s.carrier ? <div className="pf-hint">{s.carrier}</div> : null}
        </>
      ),
    },
    {
      id: "when",
      header: t("shipments.columns.when"),
      width: COLS.when,
      cell: (s) => (
        <>
          {activity(s.shipped_at)}
          {s.shipped_by ? <div className="pf-hint">{s.shipped_by}</div> : null}
        </>
      ),
    },
  ];
  return (
    <DataTable
      tableId="erp.stock.shipments"
      caption={t("shipments.caption")}
      scrollLabel={t("shipments.scroll")}
      className="pf-calc-table"
      flexMin={240}
      columns={columns}
      rows={items}
      rowKey={(s) => s.id}
    />
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
        <QueryState query={query} labels={labels} level={3} rows={10}>
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
