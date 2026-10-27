import { useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { AuditPage } from "./audit/AuditPage";
import { BusJournalPage } from "./bus/BusJournalPage";
import { BotPage } from "./bot/BotPage";
import { IntegrationsPage } from "./integrations/IntegrationsPage";
import { CompanyPage } from "./company/CompanyPage";
import { OrgPage } from "./org/OrgPage";
import { RolesPage } from "./roles/RolesPage";
import { SetupWizardPage } from "./setup/SetupWizardPage";

/**
 * Модуль Admin. Оргструктура (PLT-15), Ролевая матрица (R-2), Внешние интеграции (W13-A1), Компания (W13-A3), Журнал
 * интеграций (W13-A2), первый запуск (W13-A4) и Настройки бота (W13-A5) — настоящие экраны; остальные разделы пока заглушки каркаса.
 */
export function Component() {
  const location = useLocation();
  const match = matchSection(location.pathname, location.search);
  if (match?.module.code === "admin" && match.section.key === "org") {
    return (
      <RequireAccess rule={match.section.access}>
        <OrgPage objectId={match.objectId} />
      </RequireAccess>
    );
  }
  if (match?.module.code === "admin" && match.section.key === "roles") {
    return (
      <RequireAccess rule={match.section.access}>
        <RolesPage />
      </RequireAccess>
    );
  }
  if (match?.module.code === "admin" && match.section.key === "audit") {
    return (
      <RequireAccess rule={match.section.access}>
        <AuditPage />
      </RequireAccess>
    );
  }
  if (match?.module.code === "admin" && match.section.key === "integrations") {
    return (
      <RequireAccess rule={match.section.access}>
        <IntegrationsPage />
      </RequireAccess>
    );
  }
  if (match?.module.code === "admin" && match.section.key === "company") {
    return (
      <RequireAccess rule={match.section.access}>
        <CompanyPage />
      </RequireAccess>
    );
  }
  if (match?.module.code === "admin" && match.section.key === "bus") {
    return (
      <RequireAccess rule={match.section.access}>
        <BusJournalPage />
      </RequireAccess>
    );
  }
  if (match?.module.code === "admin" && match.section.key === "setup") {
    return (
      <RequireAccess rule={match.section.access}>
        <SetupWizardPage />
      </RequireAccess>
    );
  }
  if (match?.module.code === "admin" && match.section.key === "bot") {
    return (
      <RequireAccess rule={match.section.access}>
        <BotPage />
      </RequireAccess>
    );
  }
  return <ModuleRoutes />;
}
