import { Card } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { ExportsView } from "../bot/ExportsView";
import { SoloSection } from "../company/solo";
import { NumberingTab } from "../company/tabs/NumberingTab";
import { PlatformTab } from "../company/tabs/PlatformTab";
import { AiTab } from "../docflow/AiTab";
import { TemplatesTab as ResolutionTemplates } from "../docflow/TemplatesTab";
import { MailPanel } from "../integrations/MailPanel";
import { SpendPanel } from "../integrations/SpendPanel";
import { BotSettingsSections } from "./BotSettingsSections";
import { SettingsPage } from "./SettingsPage";

import "../company/company.css";
import "../docflow/docflow.css";
import "../integrations/integrations.css";

/** Страница из одной части прежней вкладки «Компании и бланков» или «Документооборота»: карточка без своего заголовка. */
function Solo({ children }: { children: React.ReactNode }) {
  return (
    <Card styles={{ body: { padding: 0 } }}>
      <SoloSection.Provider value={true}>{children}</SoloSection.Provider>
    </Card>
  );
}

/** Компания · Нумерация (бывшая вкладка «Компании и бланков»). */
export function NumberingPage() {
  return (
    <SettingsPage sectionKey="numbering">
      <Solo>
        <NumberingTab />
      </Solo>
    </SettingsPage>
  );
}

/** Компания · Налоги и валюты: НДС и курс USD → валюта компании (бывшая вкладка «Платформа»). */
export function TaxesPage() {
  return (
    <SettingsPage sectionKey="taxes">
      <Solo>
        <PlatformTab />
      </Solo>
    </SettingsPage>
  );
}

/** Каналы связи · Почта: отправка (SMTP), приём в общий ящик (IMAP), журнал доставки — бывшая карточка «Подключений». */
export function MailPage() {
  const { me } = useAuth();
  return (
    <SettingsPage sectionKey="mail">
      <Card>
        <MailPanel editable={canEdit(me, "admin")} titled={false} />
      </Card>
    </SettingsPage>
  );
}

/** Каналы связи · Формы сайта: форма «Заявка» и её защита от спама (раздел `web_form` настроек бота). */
export function WebFormsPage() {
  return (
    <SettingsPage sectionKey="forms">
      <BotSettingsSections page="forms" />
    </SettingsPage>
  );
}

/** Процессы · Шаблоны резолюций (бывшая вкладка «Документооборота»). */
export function ResolutionsPage() {
  const { me } = useAuth();
  return (
    <SettingsPage sectionKey="resolutions">
      <Solo>
        <ResolutionTemplates readOnly={!canEdit(me, "admin")} />
      </Solo>
    </SettingsPage>
  );
}

/** Процессы · Время и сроки: рабочие часы и правила передачи менеджеру со сроком ответа (SLA). */
export function TimingPage() {
  return (
    <SettingsPage sectionKey="timing">
      <BotSettingsSections page="timing" />
    </SettingsPage>
  );
}

/** Процессы · Уведомления: канал команды и оповещения о сбоях; личные уведомления — в Профиле. */
export function NotificationsPage() {
  const { t } = useTranslation("modules");
  return (
    <SettingsPage
      sectionKey="notifications"
      subtitle={
        <>
          {t("admin.notifications.personal")}{" "}
          <Link className="pf-focusable pf-set-inline" to="/me?part=notifications">
            {t("admin.notifications.profile")}
          </Link>
        </>
      }
    >
      <BotSettingsSections page="notifications" />
    </SettingsPage>
  );
}

/** Система · Расходы на ИИ: отчёт, дневной лимит и ИИ-помощник в документах. */
export function AiSpendPage() {
  return (
    <SettingsPage sectionKey="spend">
      <Card>
        <SpendPanel titled={false} />
      </Card>
      <BotSettingsSections page="spend" />
      <Card styles={{ body: { padding: 0 } }}>
        <AiTab />
      </Card>
    </SettingsPage>
  );
}

/** Система · Выгрузки: лиды, клиенты и сделки в CSV (бывшая вкладка «Telegram-бота»). */
export function ExportsPage() {
  return (
    <SettingsPage sectionKey="exports">
      <ExportsView />
    </SettingsPage>
  );
}
