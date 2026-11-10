import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { SectionTabs } from "../../admin/company/SectionTabs";
import { BrigadesPanel } from "./BrigadesPanel";
import { ItemsPanel } from "./ItemsPanel";
import { PriceImportPanel } from "./PriceImportPanel";
import { RefsPanel } from "./RefsPanel";

import "../../admin/company/company.css";
import "./catalog.css";

const PARTS = ["items", "brigades", "refs"] as const;
type Part = (typeof PARTS)[number];

/**
 * Каталог · Товары (`/erp/catalog`, SPEC-v3 §7.4 «Справочники», D2-3): позиции, загрузка прайса партнёра (`?part=import`,
 * CAT-1), бригады и исполнители услуг, справочники (курсы, ТН ВЭД, производители) и запросы на новые категории. Раздел
 * `erp.stock`; цены поставщиков и ставки бригад ERP отдаёт только по праву (поля `supplier_prices`, `cost_margin`).
 */
export function CatalogScreen() {
  const { t } = useTranslation(["catalog", "modules"]);
  useDocumentTitle(t("modules:erp.sections.catalog"));
  const [params, setParams] = useSearchParams();
  const requested = params.get("part");
  // Старый адрес вкладки «Запросы на категории» открывает её в справочниках
  const part: Part =
    requested === "requests" ? "refs" : (PARTS.find((p) => p === requested) ?? "items");
  if (requested === "import") {
    return (
      <div className="pf-cat">
        <PageHeader
          title={t("catalog:tabs.import")}
          extra={<LinkButton to="/erp/catalog">{t("catalog:backToItems")}</LinkButton>}
        />
        <PriceImportPanel />
      </div>
    );
  }
  const panels: Record<Part, React.ReactNode> = {
    items: <ItemsPanel />,
    brigades: <BrigadesPanel />,
    refs: <RefsPanel initial={requested === "requests" ? "requests" : "hs"} />,
  };
  return (
    <div className="pf-cat">
      <PageHeader title={t("modules:erp.sections.catalog")} subtitle={t("catalog:subtitle")} />
      <SectionTabs
        label={t("catalog:tabs.label")}
        active={part}
        tabs={PARTS.map((key) => ({ key, label: t(`catalog:tabs.${key}`) }))}
        onChange={(key) => {
          setParams({ part: key });
        }}
      >
        {panels[part]}
      </SectionTabs>
    </div>
  );
}
