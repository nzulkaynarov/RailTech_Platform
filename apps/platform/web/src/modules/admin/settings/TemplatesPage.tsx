import { Card } from "antd";
import { useTranslation } from "react-i18next";

import { SectionTabs } from "../company/SectionTabs";
import { DocumentTemplates } from "../company/tabs/DocumentTemplates";
import { EmailTemplates } from "../company/tabs/EmailTemplates";
import { QuoteTab } from "../company/tabs/QuoteTab";
import { SettingsPage } from "./SettingsPage";
import { useTabParam } from "./useTabParam";

import "../company/company.css";

const TABS = ["documents", "emails", "quote"] as const;

/**
 * Процессы · Шаблоны документов (SET-IA): шаблоны КП, договоров, счетов и актов, шаблоны писем клиентам и условия КП по
 * умолчанию — бывшие вкладки «Шаблоны» и «Условия КП» «Компании и бланков». Один уровень вкладок, `?tab=`.
 */
export function TemplatesPage() {
  const { t } = useTranslation("company");
  const [active, select] = useTabParam(TABS);
  return (
    <SettingsPage sectionKey="templates">
      <Card styles={{ body: { padding: 0 } }}>
        <SectionTabs
          label={t("templates.part")}
          active={active}
          onChange={select}
          tabs={TABS.map((key) => ({
            key,
            label: key === "quote" ? t("tabs.quote") : t(`templates.parts.${key}`),
          }))}
        >
          {active === "documents" ? (
            <div className="pf-co-body">
              <DocumentTemplates />
            </div>
          ) : active === "emails" ? (
            <div className="pf-co-body">
              <EmailTemplates />
            </div>
          ) : (
            <QuoteTab />
          )}
        </SectionTabs>
      </Card>
    </SettingsPage>
  );
}
