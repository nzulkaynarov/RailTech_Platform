import { Navigate, useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { ClientsPage } from "./clients/ClientsPage";
import { KbPage } from "./kb/KbPage";
import { LeadsPage } from "./leads/LeadsPage";

/**
 * Модуль CRM. «База знаний» (W13-A5), «Ждут ответа» (D1-1), «Лиды» и «Клиенты» (D1-2b) — настоящие экраны; остальные
 * разделы пока заглушки каркаса.
 */
export function Component() {
  const location = useLocation();
  const match = matchSection(location.pathname, location.search);
  if (match?.module.code !== "crm") return <ModuleRoutes />;
  const key = match.section.key;
  // Старые разделы без экрана: заявки — в «Операциях», подключение бота — в настройках Telegram
  if (key === "requests") return <Navigate to="/erp/requests" replace />;
  if (key === "channels") return <Navigate to="/admin/telegram" replace />;
  // «Ждут ответа» — фильтр «Лидов»: старые ссылки из колокольчика и задач ведут туда же
  if (key === "messages") {
    const lead = new URLSearchParams(location.search).get("lead");
    return (
      <Navigate
        to={`/crm/leads?scope=waiting${lead ? `&lead=${encodeURIComponent(lead)}` : ""}`}
        replace
      />
    );
  }
  const page =
    key === "kb" ? (
      <KbPage />
    ) : key === "leads" ? (
      <LeadsPage objectId={match.objectId} />
    ) : key === "clients" ? (
      <ClientsPage objectId={match.objectId} />
    ) : null;
  if (page === null) return <ModuleRoutes />;
  return <RequireAccess rule={match.section.access}>{page}</RequireAccess>;
}
