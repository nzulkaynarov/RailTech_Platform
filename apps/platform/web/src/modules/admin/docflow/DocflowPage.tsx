import { Alert, Card } from "antd";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { SectionTabs } from "../company/SectionTabs";
import { AiTab } from "./AiTab";
import { DictionariesTab } from "./DictionariesTab";
import { TemplatesTab } from "./TemplatesTab";

import "../company/company.css";
import "./docflow.css";

const TABS = [{ key: "dictionaries" }, { key: "templates" }, { key: "ai" }] as const;

type TabKey = (typeof TABS)[number]["key"];
const isTab = (value: string | null): value is TabKey => TABS.some((tab) => tab.key === value);

/**
 * Настройки · Документооборот (EDS-REG): справочники писем как данные — виды входящих документов и способы получения
 * (`/dictionaries…`), и шаблоны резолюций (R2). Разделы — вкладками (`?tab=`). Менять может
 * `admin: full`, директор (`admin: read`) только смотрит.
 */
export function DocflowPage() {
  const { t } = useTranslation(["letters", "modules"]);
  const { me } = useAuth();
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab");
  const active: TabKey = isTab(requested) ? requested : "dictionaries";
  const title = t("modules:admin.sections.docflow");
  useDocumentTitle(title);
  const readOnly = !canEdit(me, "admin");

  return (
    <div className="pf-co">
      <PageHeader title={title} subtitle={t("letters:settings.subtitle")} />
      <Card styles={{ body: { padding: 0 } }}>
        {readOnly ? (
          <Alert
            type="info"
            showIcon
            style={{ margin: 16 }}
            message={t("letters:settings.readOnly")}
          />
        ) : null}
        <SectionTabs
          label={t("letters:settings.tabsLabel")}
          active={active}
          onChange={(key) => {
            setParams(
              (prev) => {
                const next = new URLSearchParams(prev);
                next.set("tab", key);
                return next;
              },
              { replace: true },
            );
          }}
          tabs={TABS.map(({ key }) => ({ key, label: t(`letters:settings.tabs.${key}`) }))}
        >
          {active === "templates" ? (
            <TemplatesTab readOnly={readOnly} />
          ) : active === "ai" ? (
            <AiTab readOnly={readOnly} />
          ) : (
            <DictionariesTab readOnly={readOnly} />
          )}
        </SectionTabs>
      </Card>
    </div>
  );
}
