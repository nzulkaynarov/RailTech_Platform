import { useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { ClientsPage } from "./clients/ClientsPage";
import { KbPage } from "./kb/KbPage";
import { LeadsPage } from "./leads/LeadsPage";
import { MessagesPage } from "./messages/MessagesPage";

/**
 * Модуль CRM. «База знаний» (W13-A5), «Ждут ответа» (D1-1), «Лиды» и «Клиенты» (D1-2b) — настоящие экраны; остальные
 * разделы пока заглушки каркаса.
 */
export function Component() {
  const location = useLocation();
  const match = matchSection(location.pathname, location.search);
  if (match?.module.code !== "crm") return <ModuleRoutes />;
  const key = match.section.key;
  const page =
    key === "kb" ? (
      <KbPage />
    ) : key === "messages" ? (
      <MessagesPage />
    ) : key === "leads" ? (
      <LeadsPage objectId={match.objectId} />
    ) : key === "clients" ? (
      <ClientsPage objectId={match.objectId} />
    ) : null;
  if (page === null) return <ModuleRoutes />;
  return <RequireAccess rule={match.section.access}>{page}</RequireAccess>;
}
