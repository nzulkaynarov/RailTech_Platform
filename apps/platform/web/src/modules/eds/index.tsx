import { useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { InboxScreen } from "./inbox/InboxScreen";

/**
 * Модуль EDS. «Входящие письма» (D1-3) — настоящий экран: список, карточка письма и «Резолюция» директора; остальные разделы
 * пока заглушки каркаса.
 */
export function Component() {
  const location = useLocation();
  const match = matchSection(location.pathname, location.search);
  if (match?.module.code === "eds" && match.section.key === "inbox") {
    return (
      <RequireAccess rule={match.section.access}>
        <InboxScreen objectId={match.objectId} />
      </RequireAccess>
    );
  }
  return <ModuleRoutes />;
}
