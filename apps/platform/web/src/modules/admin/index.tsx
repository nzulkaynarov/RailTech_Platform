import type { ComponentType } from "react";
import { Navigate, useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { ArticlesPage } from "./articles/ArticlesPage";
import { AuditPage } from "./audit/AuditPage";
import { BusJournalPage } from "./bus/BusJournalPage";
import { CompanyPage } from "./company/CompanyPage";
import { IntegrationsPage } from "./integrations/IntegrationsPage";
import { OrgPage } from "./org/OrgPage";
import { legacySettingsPath } from "./redirects";
import { RolesPage } from "./roles/RolesPage";
import { SigningPage } from "./signing/SigningPage";
import { DictionariesPage } from "./settings/DictionariesPage";
import {
  AiSpendPage,
  ExportsPage,
  MailPage,
  NotificationsPage,
  NumberingPage,
  ResolutionsPage,
  TaxesPage,
  TimingPage,
  WebFormsPage,
} from "./settings/pages";
import { SettingsHome } from "./settings/SettingsHome";
import { TelegramPage } from "./settings/TelegramPage";
import { TemplatesPage } from "./settings/TemplatesPage";
import { SetupWizardPage } from "./setup/SetupWizardPage";
import { TicketsPage } from "./tickets/TicketsPage";

/** Страницы разделов без своего номера объекта; ключ — раздел модуля (`module.ts`, реестр настроек). */
const PAGES: Readonly<Record<string, ComponentType>> = {
  overview: SettingsHome,
  roles: RolesPage,
  signing: SigningPage,
  company: CompanyPage,
  numbering: NumberingPage,
  taxes: TaxesPage,
  articles: ArticlesPage,
  telegram: TelegramPage,
  mail: MailPage,
  forms: WebFormsPage,
  dictionaries: DictionariesPage,
  resolutions: ResolutionsPage,
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
  const legacy = legacySettingsPath(location.pathname, location.search);
  if (legacy) return <Navigate to={legacy} replace />;
  const match = matchSection(location.pathname, location.search);
  if (match?.module.code !== "admin") return <ModuleRoutes />;
  const { section, objectId } = match;
  if (section.key === "org") {
    return (
      <RequireAccess rule={section.access}>
        <OrgPage objectId={objectId} />
      </RequireAccess>
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
    <RequireAccess rule={section.access}>
      <Page />
    </RequireAccess>
  );
}
