import { useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { ApprovalsScreen } from "./approvals/ApprovalsScreen";
import { DocumentsPage } from "./documents/DocumentsPage";
import { DraftsScreen } from "./drafts/DraftsScreen";
import { InboxScreen } from "./inbox/InboxScreen";
import { NewDocumentPage } from "./new/NewDocumentPage";

/**
 * Модуль EDS. «Входящие письма» (D1-3), «Все документы» (реестр и «Мои документы») и «Создать документ» (D1-5), «КП на одобрение»
 * и «На согласовании» (D1-4) — настоящие экраны; остальные разделы пока заглушки каркаса.
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
  if (match?.module.code === "eds" && match.section.key === "drafts") {
    return (
      <RequireAccess rule={match.section.access}>
        <DraftsScreen objectId={match.objectId} />
      </RequireAccess>
    );
  }
  if (match?.module.code === "eds" && match.section.key === "approvals") {
    return (
      <RequireAccess rule={match.section.access}>
        <ApprovalsScreen objectId={match.objectId} />
      </RequireAccess>
    );
  }
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
