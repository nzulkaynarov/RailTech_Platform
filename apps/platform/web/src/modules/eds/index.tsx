import { useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { DocumentsPage } from "./documents/DocumentsPage";
import { NewDocumentPage } from "./new/NewDocumentPage";

/**
 * Модуль EDS. «Все документы» (реестр и «Мои документы») и «Создать документ» (D1-5) — настоящие экраны; остальные
 * разделы пока заглушки каркаса.
 */
export function Component() {
  const location = useLocation();
  const match = matchSection(location.pathname, location.search);
  if (match?.module.code === "eds" && match.section.key === "documents") {
    return (
      <RequireAccess rule={match.section.access}>
        <DocumentsPage />
      </RequireAccess>
    );
  }
  if (match?.module.code === "eds" && match.section.key === "new") {
    return (
      <RequireAccess rule={match.section.access}>
        <NewDocumentPage />
      </RequireAccess>
    );
  }
  return <ModuleRoutes />;
}
