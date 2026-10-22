import { useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { OrgPage } from "./org/OrgPage";

/**
 * Модуль Admin. Оргструктура — настоящий экран (PLT-15); остальные разделы пока страницы-заглушки каркаса.
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
  return <ModuleRoutes />;
}
