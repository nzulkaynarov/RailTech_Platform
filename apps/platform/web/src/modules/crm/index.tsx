import { useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { KbPage } from "./kb/KbPage";
import { MessagesPage } from "./messages/MessagesPage";

/**
 * Модуль CRM. «База знаний» (W13-A5) и «Ждут ответа» (D1-1) — настоящие экраны; остальные разделы пока заглушки каркаса.
 */
export function Component() {
  const location = useLocation();
  const match = matchSection(location.pathname, location.search);
  if (match?.module.code === "crm" && match.section.key === "kb") {
    return (
      <RequireAccess rule={match.section.access}>
        <KbPage />
      </RequireAccess>
    );
  }
  if (match?.module.code === "crm" && match.section.key === "messages") {
    return (
      <RequireAccess rule={match.section.access}>
        <MessagesPage />
      </RequireAccess>
    );
  }
  return <ModuleRoutes />;
}
