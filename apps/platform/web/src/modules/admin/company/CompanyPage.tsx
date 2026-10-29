import { Alert, Card } from "antd";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { PanelPortal } from "../../../app/shell/PanelSlot";
import { useGetCompany, useGetNumberingScheme } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { SectionTabs } from "./SectionTabs";
import { BrandTab } from "./tabs/BrandTab";
import { CategoriesTab } from "./tabs/CategoriesTab";
import { ChargesTab } from "./tabs/ChargesTab";
import { DetailsTab } from "./tabs/DetailsTab";
import { NumberingTab } from "./tabs/NumberingTab";
import { PlatformTab } from "./tabs/PlatformTab";
import { QuoteTab } from "./tabs/QuoteTab";
import { ReferenceTab } from "./tabs/ReferenceTab";
import { TemplatesTab } from "./tabs/TemplatesTab";

import "./company.css";

const TABS = [
  { key: "details", Content: DetailsTab },
  { key: "brand", Content: BrandTab },
  { key: "numbering", Content: NumberingTab },
  { key: "quote", Content: QuoteTab },
  { key: "charges", Content: ChargesTab },
  { key: "templates", Content: TemplatesTab },
  { key: "reference", Content: ReferenceTab },
  { key: "categories", Content: CategoriesTab },
  { key: "platform", Content: PlatformTab },
] as const;

type TabKey = (typeof TABS)[number]["key"];
const isTab = (value: string | null): value is TabKey => TABS.some((tab) => tab.key === value);

/** Боковое окно «Карточка»: сводка по своей компании, пока открыта любая вкладка настроек. */
function CompanySummary() {
  const { t } = useTranslation("company");
  const company = useGetCompany();
  const scheme = useGetNumberingScheme();
  if (!company.data) return null;
  return (
    <div className="pf-panel-stack">
      <h3 style={{ margin: 0, fontSize: 16, lineHeight: "24px", fontWeight: 600 }}>
        {company.data.name}
      </h3>
      <DefinitionList
        items={[
          { label: t("details.inn"), value: company.data.inn },
          { label: t("details.phone"), value: company.data.phone },
          { label: t("details.email"), value: company.data.email },
          { label: t("numbering.prefix"), value: scheme.data?.prefix },
        ]}
      />
    </div>
  );
}

/**
 * Admin · Компания (SPEC-v3 §7.6, W13-A3): настройки своей компании в ERP — реквизиты и логотип, бланк и бренд, нумерация,
 * условия КП, статьи расхода, шаблоны, справочники, категории каталога и платформенные настройки. Разделы — вкладками
 * (`?tab=`). Раздел `company.settings`: администратор и директор — полный доступ; при доступе «чтение» все поля заблокированы.
 */
export function CompanyPage() {
  const { t } = useTranslation(["company", "modules"]);
  const { me } = useAuth();
  const [params, setParams] = useSearchParams();
  const requested = params.get("viewTab") ?? params.get("tab");
  const active: TabKey = isTab(requested) ? requested : "details";
  const readOnly = !canEdit(me, "company.settings");
  const company = useGetCompany();
  const title = t("modules:admin.sections.company");
  useDocumentTitle(title);

  return (
    <div className="pf-co">
      <PageHeader title={title} subtitle={company.data?.name ?? t("company:subtitle")} />
      <Card styles={{ body: { padding: 0 } }}>
        {readOnly ? (
          <Alert type="info" showIcon style={{ margin: 16 }} message={t("company:readOnly")} />
        ) : null}
        <SectionTabs
          label={t("company:tabsLabel")}
          active={active}
          onChange={(key) => {
            setParams(
              (prev) => {
                const next = new URLSearchParams(prev);
                next.set("viewTab", key);
                next.set("tab", key);
                return next;
              },
              { replace: true },
            );
          }}
          tabs={TABS.map(({ key }) => ({ key, label: t(`company:tabs.${key}`) }))}
        >
          {(() => {
            const Content = TABS.find((tab) => tab.key === active)?.Content ?? DetailsTab;
            return <Content />;
          })()}
        </SectionTabs>
      </Card>
      <PanelPortal tab="card">
        <CompanySummary />
      </PanelPortal>
    </div>
  );
}
