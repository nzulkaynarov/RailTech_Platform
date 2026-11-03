import { Alert, Card } from "antd";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { canEdit, canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { PanelPortal } from "../../../app/shell/PanelSlot";
import { useGetCompany, useGetNumberingScheme } from "../../../shared/api/generated/platform-bff";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { BotSettingsSections } from "../settings/BotSettingsSections";
import { SettingsPage } from "../settings/SettingsPage";
import { BrandTab } from "./tabs/BrandTab";
import { DetailsTab } from "./tabs/DetailsTab";

import "./company.css";

/** Части страницы, к которым ведут старые ссылки (`?part=brand` — бывшая вкладка «Бланк и бренд»). */
const PARTS = ["details", "brand", "contacts"] as const;

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
 * Компания · Реквизиты и бланк (SPEC-v3 §7.6, W13-A3; SET-IA): одна страница с частями вместо девяти вкладок — реквизиты и
 * логотип, бланк и бренд документов, контакты, которые бот называет клиентам (раздел `company` настроек бота; одни реквизиты
 * на всю платформу — этап 2, BACKLOG). Нумерация, налоги, шаблоны и справочники — свои страницы групп «Компания» и «Процессы».
 * `company.settings`: администратор и директор — полный доступ; при доступе «чтение» поля заблокированы.
 */
export function CompanyPage() {
  const { t } = useTranslation(["company", "modules"]);
  const { me } = useAuth();
  const [params] = useSearchParams();
  const readOnly = !canEdit(me, "company.settings");
  const company = useGetCompany();
  const part = params.get("part");

  // Старая ссылка на вкладку ведёт к своей части страницы.
  useEffect(() => {
    if (!part || !PARTS.includes(part as (typeof PARTS)[number])) return;
    document.getElementById(`pf-co-part-${part}`)?.scrollIntoView({ block: "start" });
  }, [part]);

  return (
    <SettingsPage sectionKey="company" subtitle={company.data?.name}>
      {readOnly ? <Alert type="info" showIcon message={t("company:readOnly")} /> : null}
      <Card id="pf-co-part-details" styles={{ body: { padding: 0 } }}>
        <DetailsTab />
      </Card>
      <Card id="pf-co-part-brand" styles={{ body: { padding: 0 } }}>
        <BrandTab />
      </Card>
      {canSee(me, { resource: "admin" }) ? (
        <section id="pf-co-part-contacts" className="pf-panel-stack">
          <BotSettingsSections page="company" />
        </section>
      ) : null}
      <PanelPortal tab="card">
        <CompanySummary />
      </PanelPortal>
    </SettingsPage>
  );
}
