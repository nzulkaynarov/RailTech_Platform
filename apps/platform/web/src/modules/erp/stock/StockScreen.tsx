import type React from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { DataBlock } from "../../../shared/ui/DataBlock";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { TabsBar } from "../../../shared/ui/TabsBar";
import { BalancesTab } from "./BalancesTab";
import { OrdersTab } from "./OrdersTab";
import { ReceiptsTab } from "./ReceiptsTab";
import { ShipmentsTab } from "./ShipmentsTab";

import "../calc/calc.css";
import "./stock.css";

const VIEWS = ["balances", "orders", "receipts", "shipments"] as const;
type View = (typeof VIEWS)[number];

const BODY: Record<View, () => React.ReactNode> = {
  balances: () => <BalancesTab />,
  orders: () => <OrdersTab />,
  receipts: () => <ReceiptsTab />,
  shipments: () => <ShipmentsTab />,
};

function viewOf(value: string | null): View {
  return VIEWS.find((v) => v === value) ?? "balances";
}

/**
 * Расчёт · «Склад» (SPEC-v3 §7.4): остатки и резервы по номенклатуре (ячейка, свободный остаток, резерв под проект),
 * заказы поставщикам (ЗП-номер, поставщик, ожидаемая дата, статус), приёмка от поставщика по строкам и отгрузки по проектам
 * (внутренняя накладная, трек). Вкладка — в адресе (`?view=`), чтобы на неё можно было сослаться из «Моих задач».
 */
export function StockScreen() {
  const { t } = useTranslation("stock");
  const [params, setParams] = useSearchParams();
  const view = viewOf(params.get("view"));
  useDocumentTitle(t("title"));
  return (
    <div className="pf-calc pf-stock">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />
      <TabsBar
        id="pf-stock-tabs"
        label={t("title")}
        activeKey={view}
        onChange={(key) => {
          setParams(
            (prev) => {
              const next = new URLSearchParams(prev);
              next.set("view", key);
              next.delete("overdue");
              return next;
            },
            { replace: true },
          );
        }}
        items={VIEWS.map((key) => ({ key, label: t(`tabs.${key}`) }))}
      >
        {/* Вкладка ещё не загружена — блок держит высоту прежней, пока виден скелетон (UX-1c, S8). */}
        <DataBlock>{BODY[view]()}</DataBlock>
      </TabsBar>
    </div>
  );
}
