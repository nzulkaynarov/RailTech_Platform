import type { ComponentType } from "react";
import { useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { ArticlesPage } from "./articles/ArticlesPage";
import { AuditPage } from "./audit/AuditPage";
import { BusJournalPage } from "./bus/BusJournalPage";
import { CompanyPage } from "./company/CompanyPage";
import { IntegrationsPage } from "./integrations/IntegrationsPage";
import { LegalPage } from "./legal/LegalPage";
import { OrgPage } from "./org/OrgPage";
import { RolesPage } from "./roles/RolesPage";
import { SigningPage } from "./signing/SigningPage";
import { ZonesPage } from "./zones/ZonesPage";
import { DictionariesPage } from "./settings/DictionariesPage";
import {
  AiSpendPage,
  ExportsPage,
  MailPage,
  NotificationsPage,
  NumberingPage,
  SalesPage,
  TaxesPage,
  TimingPage,
  WebFormsPage,
} from "./settings/pages";
import { SettingsFrame } from "./settings/SettingsFrame";
import { TelegramPage } from "./settings/TelegramPage";
import { TemplatesPage } from "./settings/TemplatesPage";
import { SetupWizardPage } from "./setup/SetupWizardPage";
import { StatePage } from "./state/StatePage";
import { TicketsPage } from "./tickets/TicketsPage";

/** Страницы разделов без своего номера объекта; ключ — раздел модуля (`module.ts`, реестр настроек). */
const PAGES: Readonly<Record<string, ComponentType>> = {
  overview: StatePage,
  roles: RolesPage,
  signing: SigningPage,
  zones: ZonesPage,
  company: CompanyPage,
  numbering: NumberingPage,
  taxes: TaxesPage,
  sales: SalesPage,
  articles: ArticlesPage,
  legal: LegalPage,
  telegram: TelegramPage,
  mail: MailPage,
  forms: WebFormsPage,
  dictionaries: DictionariesPage,
  templates: TemplatesPage,
  timing: TimingPage,
  notifications: NotificationsPage,
  integrations: IntegrationsPage,
  spend: AiSpendPage,
  audit: AuditPage,
  exports: ExportsPage,
  bus: BusJournalPage,
  setup: SetupWizardPage,
};

/**
 * Модуль Admin — Настройки (SET-IA): индекс с поиском и пять групп страниц. Старые адреса (Telegram-бот, Компания и бланки,
 * Документооборот, список обращений, карточки «Подключений» с своей страницей) уводятся на новые без лишней записи в историю.
 */
export function Component() {
  const location = useLocation();
  const match = matchSection(location.pathname, location.search);
  if (match?.module.code !== "admin") return <ModuleRoutes />;
  const { section, objectId } = match;
  if (section.key === "org") {
    return (
      <SettingsFrame>
        <RequireAccess rule={section.access}>
          <OrgPage objectId={objectId} />
        </RequireAccess>
      </SettingsFrame>
    );
  }
  if (section.key === "tickets") {
    return (
      <RequireAccess rule={section.access}>
        <TicketsPage objectId={objectId} />
      </RequireAccess>
    );
  }
  const Page = PAGES[section.key];
  if (!Page) return <ModuleRoutes />;
  return (
    <SettingsFrame>
      <RequireAccess rule={section.access}>
        <Page />
      </RequireAccess>
    </SettingsFrame>
  );
}
