import { Card } from "antd";
import { useTranslation } from "react-i18next";

import { SectionTabs } from "../company/SectionTabs";
import { ContractTemplates } from "../company/tabs/ContractTemplates";
import { DocumentTemplates } from "../company/tabs/DocumentTemplates";
import { EmailTemplates } from "../company/tabs/EmailTemplates";
import { LetterTemplates } from "../company/tabs/LetterTemplates";
import { SettingsPage } from "./SettingsPage";
import { TemplateCatalog } from "./TemplateCatalog";
import { useTabParam } from "./useTabParam";

import "../company/company.css";

const TABS = ["all", "documents", "contracts", "letters", "emails"] as const;

/**
 * Процессы · Шаблоны документов (SET-IA): шаблоны КП, договоров, счетов и актов, шаблоны писем клиентам. «Условия КП» — не шаблон,
 * они на страницах «Продажи», «Налоги и валюты» и «Уведомления» (ДОК-13). Один уровень вкладок, `?tab=`.
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
            label:
              key === "all"
                ? t("catalog.tab")
                : key === "letters"
                  ? t("letterTemplates.tab")
                  : t(`templates.parts.${key}`),
          }))}
        >
          {active === "all" ? (
            <div className="pf-co-body">
              <TemplateCatalog />
            </div>
          ) : active === "documents" ? (
            <div className="pf-co-body">
              <DocumentTemplates />
            </div>
          ) : active === "contracts" ? (
            <div className="pf-co-body">
              <ContractTemplates />
            </div>
          ) : active === "letters" ? (
            <div className="pf-co-body">
              <LetterTemplates />
            </div>
          ) : (
            <div className="pf-co-body">
              <EmailTemplates />
            </div>
          )}
        </SectionTabs>
      </Card>
    </SettingsPage>
  );
}
