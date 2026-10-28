import { useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { CatalogScreen } from "./catalog/CatalogScreen";
import { DocsScreen } from "./docs/DocsScreen";

/**
 * Модуль ERP («Расчёт»). «Номенклатура и поставщики» и «Техдокументация» (D2-3) — настоящие экраны; остальные разделы
 * пока заглушки каркаса.
 */
export function Component() {
  const location = useLocation();
  const match = matchSection(location.pathname, location.search);
  if (match?.module.code === "erp" && match.section.key === "catalog") {
    return (
      <RequireAccess rule={match.section.access}>
        <CatalogScreen />
      </RequireAccess>
    );
  }
  if (match?.module.code === "erp" && match.section.key === "docs") {
    return (
      <RequireAccess rule={match.section.access}>
        <DocsScreen />
      </RequireAccess>
    );
  }
  return <ModuleRoutes />;
}
