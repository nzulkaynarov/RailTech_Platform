import { Tabs } from "antd";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { BalancesTab } from "./BalancesTab";
import { OrdersTab } from "./OrdersTab";
import { ReceiptsTab } from "./ReceiptsTab";
import { ShipmentsTab } from "./ShipmentsTab";

import "../calc/calc.css";
import "./stock.css";

const VIEWS = ["balances", "orders", "receipts", "shipments"] as const;
type View = (typeof VIEWS)[number];

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
      <Tabs
        activeKey={view}
        destroyOnHidden
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
        items={[
          { key: "balances", label: t("tabs.balances"), children: <BalancesTab /> },
          { key: "orders", label: t("tabs.orders"), children: <OrdersTab /> },
          { key: "receipts", label: t("tabs.receipts"), children: <ReceiptsTab /> },
          { key: "shipments", label: t("tabs.shipments"), children: <ShipmentsTab /> },
        ]}
      />
    </div>
  );
}
