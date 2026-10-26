import { useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { CompanyPage } from "./company/CompanyPage";
import { OrgPage } from "./org/OrgPage";
import { RolesPage } from "./roles/RolesPage";

/**
 * Модуль Admin. Оргструктура (PLT-15), Ролевая матрица (R-2) и Компания (W13-A3) — настоящие экраны; остальные разделы пока
 * заглушки каркаса.
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
  if (match?.module.code === "admin" && match.section.key === "company") {
    return (
      <RequireAccess rule={match.section.access}>
        <CompanyPage />
      </RequireAccess>
    );
  }
  return <ModuleRoutes />;
}
