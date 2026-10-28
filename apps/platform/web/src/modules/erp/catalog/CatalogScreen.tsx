import { Tabs } from "antd";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useListCatalogCategoryRequests } from "../../../shared/api/generated/platform-bff";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { BrigadesPanel } from "./BrigadesPanel";
import { ItemsPanel } from "./ItemsPanel";
import { RefsPanel } from "./RefsPanel";
import { RequestsPanel } from "./RequestsPanel";
import { SuppliersPanel } from "./SuppliersPanel";

import "./catalog.css";

const PARTS = ["items", "suppliers", "brigades", "refs", "requests"] as const;
type Part = (typeof PARTS)[number];

/**
 * Расчёт · Номенклатура и поставщики (`/erp/catalog`, SPEC-v3 §7.4 «Справочники», D2-3): позиции, поставщики со сроками
 * цен, бригады и исполнители услуг, справочники (курсы, ТН ВЭД, производители) и запросы на новые категории. Раздел
 * `erp.stock`; цены поставщиков и ставки бригад ERP отдаёт только по праву (поля `supplier_prices`, `cost_margin`).
 */
export function CatalogScreen() {
  const { t } = useTranslation(["catalog", "modules"]);
  useDocumentTitle(t("modules:erp.sections.catalog"));
  const [params, setParams] = useSearchParams();
  const requested = params.get("part");
  const part: Part = PARTS.find((p) => p === requested) ?? "items";
  const pending = useListCatalogCategoryRequests({ status: "pending" });
  const pendingCount = pending.data?.items.length ?? 0;
  const label = (key: Part) =>
    key === "requests" && pendingCount > 0
      ? t("catalog:tabs.requestsCount", { count: pendingCount })
      : t(`catalog:tabs.${key}`);
  const panels: Record<Part, React.ReactNode> = {
    items: <ItemsPanel />,
    suppliers: <SuppliersPanel />,
    brigades: <BrigadesPanel />,
    refs: <RefsPanel />,
    requests: <RequestsPanel />,
  };
  return (
    <div className="pf-cat">
      <PageHeader title={t("modules:erp.sections.catalog")} subtitle={t("catalog:subtitle")} />
      <Tabs
        activeKey={part}
        destroyOnHidden
        onChange={(key) => {
          setParams({ part: key });
        }}
        items={PARTS.map((key) => ({ key, label: label(key), children: panels[key] }))}
      />
    </div>
  );
}
