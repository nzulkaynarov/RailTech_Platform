import { Card } from "antd";
import { useTranslation } from "react-i18next";

import { canEdit, canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { TemplatesTab as ResolutionTemplates } from "../docflow/TemplatesTab";
import { SectionTabs } from "../company/SectionTabs";
import { ContractTemplates } from "../company/tabs/ContractTemplates";
import { DocumentTemplates } from "../company/tabs/DocumentTemplates";
import { EmailTemplates } from "../company/tabs/EmailTemplates";
import { LetterTemplates } from "../company/tabs/LetterTemplates";
import { SettingsPage } from "./SettingsPage";
import { TemplateCatalog } from "./TemplateCatalog";
import { useTabParam } from "./useTabParam";

import "../company/company.css";

const TABS = ["all", "documents", "contracts", "letters", "emails", "resolutions"] as const;

/**
 * Правила работы · Шаблоны (SET-IA, ЕВ-2а: «Шаблоны резолюций» — вкладка «Резолюции», её видит администратор): шаблоны КП, договоров, счетов и актов, шаблоны писем клиентам. «Условия КП» — не шаблон,
 * они на страницах «Продажи», «Налоги и валюты» и «Уведомления» (ДОК-13). Один уровень вкладок, `?tab=`.
 */
export function TemplatesPage() {
  const { t } = useTranslation("company");
  const { me } = useAuth();
  const [asked, select] = useTabParam(TABS);
  const withResolutions = canSee(me, { resource: "admin" });
  const active = asked === "resolutions" && !withResolutions ? "all" : asked;
  return (
    <SettingsPage sectionKey="templates">
      <Card styles={{ body: { padding: 0 } }}>
        <SectionTabs
          label={t("templates.part")}
          active={active}
          onChange={select}
          tabs={TABS.filter((key) => key !== "resolutions" || withResolutions).map((key) => ({
            key,
            label:
              key === "all"
                ? t("catalog.tab")
                : key === "letters"
                  ? t("letterTemplates.tab")
                  : key === "resolutions"
                    ? t("templates.parts.resolutions")
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
          ) : active === "resolutions" ? (
            <ResolutionTemplates readOnly={!canEdit(me, "admin")} />
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
