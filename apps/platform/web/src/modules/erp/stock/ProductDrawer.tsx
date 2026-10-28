import { App, Button, Drawer, Popconfirm } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { StockRow } from "../../../shared/api/generated/model";
import {
  useGetStockProduct,
  useReleaseStockReservation,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { QueryState } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { AdjustModal } from "./AdjustModal";
import { orderPath, useErrorText, useRefreshStock, useStateLabels } from "./api";
import { useState } from "react";

/** Товар на складе: ячейки, резервы по проектам, ожидаемый приход, последние движения; «Оприходовать / списать». */
export function ProductDrawer({ row, onClose }: { row: StockRow; onClose: () => void }) {
  const { t } = useTranslation("stock");
  const { date, activity } = useFormat();
  const { message } = App.useApp();
  const refresh = useRefreshStock();
  const errorText = useErrorText();
  const labels = useStateLabels();
  const [adjusting, setAdjusting] = useState(false);
  const query = useGetStockProduct(row.product_id);
  const release = useReleaseStockReservation({
    mutation: {
      onSuccess: () => {
        refresh();
        void message.success(t("product.released"));
      },
      onError: (error) => {
        void message.error(errorText(error));
      },
    },
  });
  return (
    <Drawer open width={560} title={row.name} onClose={onClose} destroyOnHidden>
      <QueryState query={query} labels={labels}>
        {(product) => (
          <div className="pf-calc-stack">
            <p className="pf-hint pf-num">{product.article}</p>
            <dl className="pf-stock-numbers">
              <div>
                <dt>{t("balances.columns.onHand")}</dt>
                <dd className="pf-num">{product.on_hand}</dd>
              </div>
              <div>
                <dt>{t("balances.columns.reserved")}</dt>
                <dd className="pf-num">{product.reserved}</dd>
              </div>
              <div>
                <dt>{t("balances.columns.free")}</dt>
                <dd className="pf-num">{product.free}</dd>
              </div>
              <div>
                <dt>{t("balances.columns.incoming")}</dt>
                <dd className="pf-num">{product.incoming}</dd>
              </div>
            </dl>
            {product.rights.manage ? (
              <div>
                <Button
                  onClick={() => {
                    setAdjusting(true);
                  }}
                >
                  {t("product.adjust")}
                </Button>
              </div>
            ) : null}
            <section aria-labelledby="pf-stock-cells">
              <h3 id="pf-stock-cells" className="pf-calc-subtitle">
                {t("product.cells")}
              </h3>
              {product.cells.length === 0 ? (
                <p className="pf-hint">{t("product.noCells")}</p>
              ) : (
                <ul className="pf-stock-list">
                  {product.cells.map((c, index) => (
                    <li key={index}>
                      <span>{c.cell ?? t("product.noCell")}</span>
                      <span className="pf-num">{c.on_hand}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section aria-labelledby="pf-stock-reservations">
              <h3 id="pf-stock-reservations" className="pf-calc-subtitle">
                {t("product.reservations")}
              </h3>
              {product.reservations.length === 0 ? (
                <p className="pf-hint">{t("product.noReservations")}</p>
              ) : (
                <ul className="pf-stock-list">
                  {product.reservations.map((r) => (
                    <li key={r.id}>
                      <span>
                        <Link className="pf-focusable" to={r.request.path}>
                          {r.request.number}
                        </Link>
                        <span className="pf-hint"> · {r.request.client ?? "—"}</span>
                      </span>
                      <span className="pf-calc-row">
                        <span className="pf-num">{r.remaining}</span>
                        {product.rights.manage ? (
                          <Popconfirm
                            title={t("product.releaseConfirm", { number: r.request.number })}
                            okText={t("product.release")}
                            cancelText={t("common.cancel")}
                            onConfirm={() => {
                              release.mutate({ reservationId: r.id });
                            }}
                          >
                            <Button
                              size="small"
                              aria-label={t("product.releaseLabel", { number: r.request.number })}
                            >
                              {t("product.release")}
                            </Button>
                          </Popconfirm>
                        ) : null}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section aria-labelledby="pf-stock-incoming">
              <h3 id="pf-stock-incoming" className="pf-calc-subtitle">
                {t("product.incoming")}
              </h3>
              {product.incoming_orders.length === 0 ? (
                <p className="pf-hint">{t("product.noIncoming")}</p>
              ) : (
                <ul className="pf-stock-list">
                  {product.incoming_orders.map((o) => (
                    <li key={o.number}>
                      <span>
                        <Link className="pf-focusable" to={orderPath(o.number)}>
                          {o.number}
                        </Link>
                        <span className="pf-hint"> · {o.supplier}</span>
                      </span>
                      <span>
                        <span className="pf-num">+{o.quantity_left}</span>
                        {o.expected_date ? (
                          <span className="pf-hint">
                            {" "}
                            · {t("balances.until", { date: date(o.expected_date) })}
                          </span>
                        ) : null}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section aria-labelledby="pf-stock-movements">
              <h3 id="pf-stock-movements" className="pf-calc-subtitle">
                {t("product.movements")}
              </h3>
              {product.movements.length === 0 ? (
                <p className="pf-hint">{t("product.noMovements")}</p>
              ) : (
                <ul className="pf-stock-list">
                  {product.movements.map((m, index) => (
                    <li key={index}>
                      <span>
                        <StatusTag tone={m.quantity > 0 ? "green" : "default"}>
                          {t(`product.kind.${m.kind}`)}
                        </StatusTag>
                        <span className="pf-hint">
                          {" "}
                          {[m.cell, m.by, m.note].filter(Boolean).join(" · ")}
                        </span>
                      </span>
                      <span>
                        <span className="pf-num">
                          {m.quantity > 0 ? `+${String(m.quantity)}` : String(m.quantity)}
                        </span>
                        <span className="pf-hint"> · {activity(m.at)}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </QueryState>
      {adjusting ? (
        <AdjustModal
          row={row}
          onClose={() => {
            setAdjusting(false);
          }}
        />
      ) : null}
    </Drawer>
  );
}
