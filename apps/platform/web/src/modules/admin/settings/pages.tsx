import { Card } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { canEdit, canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { ExportsView } from "../bot/ExportsView";
import { SoloSection } from "../company/solo";
import { NumberingTab } from "../company/tabs/NumberingTab";
import { PlatformTab } from "../company/tabs/PlatformTab";
import { QuoteSettings } from "../company/tabs/QuoteTab";
import { AiTab } from "../docflow/AiTab";
import { DictionariesTab } from "../docflow/DictionariesTab";
import { MailRules } from "../docflow/MailRules";
import { PiiPolicyCard } from "../docflow/PiiPolicyCard";
import { MailPanel } from "../integrations/MailPanel";
import { SpendPanel } from "../integrations/SpendPanel";
import { RatesView } from "../../erp/catalog/RefsPanel";
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

/** Компания · Налоги и валюты: НДС в новом КП и курсы валют к суму (адрес поддержки — на «Реквизитах», ЕВ-2а). */
export function TaxesPage() {
  const { me } = useAuth();
  return (
    <SettingsPage sectionKey="taxes">
      <Solo>
        <PlatformTab />
      </Solo>
      <Card styles={{ body: { padding: 0 } }}>
        <QuoteSettings group="taxes" />
      </Card>
      {canSee(me, { resource: "erp.stock" }) ? (
        <Card>
          <RatesView />
        </Card>
      ) : null}
    </SettingsPage>
  );
}

/** Компания · Продажи: условия нового КП (срок, оплата, гарантия, маржа, базис) и политика каталога — бывшие «Условия КП». */
export function SalesPage() {
  return (
    <SettingsPage sectionKey="sales">
      <Card styles={{ body: { padding: 0 } }}>
        <QuoteSettings group="sales" />
      </Card>
      <Card styles={{ body: { padding: 0 } }}>
        <QuoteSettings group="contracts" />
      </Card>
      <Card styles={{ body: { padding: 0 } }}>
        <QuoteSettings group="catalog" />
      </Card>
      <Card styles={{ body: { padding: 0 } }}>
        <QuoteSettings group="supplier" />
      </Card>
    </SettingsPage>
  );
}

/** Тип входящих писем: справочник «Типы входящих писем» (каталог BFF) — вид письма, по которому работает разбор ящика. */
export const MAIL_KINDS_LIST = "mail-types";

/**
 * Каналы и подключения · Почта: отправка (SMTP), приём в общий ящик (IMAP), журнал доставки, а также виды входящих писем и
 * правила отправителей — настройки самого канала (ЕВ-2а, отчёт §8.2 п. 14; раньше — «Справочники · Почта»).
 */
export function MailPage() {
  const { me } = useAuth();
  const editable = canEdit(me, "admin");
  return (
    <SettingsPage sectionKey="mail">
      <Card>
        <MailPanel editable={editable} titled={false} />
      </Card>
      <Card id="pf-mail-kinds" styles={{ body: { padding: 0 } }}>
        <DictionariesTab readOnly={!editable} kind={MAIL_KINDS_LIST} />
      </Card>
      <Card id="pf-mail-rules" styles={{ body: { padding: 0 } }}>
        <MailRules readOnly={!editable} />
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

/** Правила работы · Время и сроки: рабочие часы и срок первого ответа лиду — оба поля (бот и сайт) здесь (ЕВ-2а, отчёт §8.2 п. 7). */
export function TimingPage() {
  return (
    <SettingsPage sectionKey="timing">
      <BotSettingsSections page="timing" />
    </SettingsPage>
  );
}

/** Правила работы · Уведомления: кого оповещать, напоминания и сбои; канал команды — в Telegram, личные уведомления — в Профиле. */
export function NotificationsPage() {
  const { t } = useTranslation("modules");
  const { me } = useAuth();
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
      {canSee(me, { resource: "company.settings" }) ? (
        <Card styles={{ body: { padding: 0 } }}>
          <QuoteSettings group="reminders" />
        </Card>
      ) : null}
    </SettingsPage>
  );
}

/** Каналы и подключения · ИИ: отчёт, дневной лимит, защита данных для ИИ и ИИ-помощник в документах. */
export function AiSpendPage() {
  return (
    <SettingsPage sectionKey="spend">
      <Card>
        <SpendPanel titled={false} />
      </Card>
      <BotSettingsSections page="spend" />
      <Card styles={{ body: { padding: 0 } }}>
        <PiiPolicyCard />
      </Card>
      <Card styles={{ body: { padding: 0 } }}>
        <AiTab />
      </Card>
    </SettingsPage>
  );
}

/** Журнал · Выгрузки: лиды, клиенты и сделки в CSV (бывшая вкладка «Telegram-бота»). */
export function ExportsPage() {
  return (
    <SettingsPage sectionKey="exports">
      <ExportsView />
    </SettingsPage>
  );
}
