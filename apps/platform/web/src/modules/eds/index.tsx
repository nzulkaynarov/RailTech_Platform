import { Navigate, useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { ApprovalsScreen } from "./approvals/ApprovalsScreen";
import { DocumentsPage } from "./documents/DocumentsPage";
import { DraftsScreen } from "./drafts/DraftsScreen";
import { InboxScreen } from "./inbox/InboxScreen";
import { MailScreen } from "./mail/MailScreen";
import { NewDocumentPage } from "./new/NewDocumentPage";
import { PaymentsScreen } from "./payments/PaymentsScreen";
import { ProjectsScreen } from "./projects/ProjectsScreen";
import { RegisterLetterPage } from "./register/RegisterLetterPage";
import { TasksScreen } from "./tasks/TasksScreen";

/**
 * Модуль EDS. «Входящие письма» (D1-3), «Все документы» (реестр и «Мои документы») и «Создать документ» (D1-5), «КП на одобрение»
 * и «На согласовании» (D1-4), «Проекты: договоры и акты» (D2-5) — настоящие экраны; остальные разделы пока заглушки каркаса.
 */
/** Старые списки без пункта меню: что ждёт сотрудника — в «Задачах», остальное — в ящиках «Документов». */
function movedListPath(
  key: string,
  objectId: string | undefined,
  search: string,
): string | undefined {
  if (objectId) return undefined;
  const params = new URLSearchParams(search);
  if (key === "drafts") {
    const quote = params.get("quote");
    return quote
      ? `/eds/drafts/${encodeURIComponent(quote)}`
      : "/eds/documents?box=outgoing&kind=quote";
  }
  if (key === "approvals") {
    const memo = params.get("memo");
    return memo ? `/eds/approvals/${encodeURIComponent(memo)}` : "/eds/documents?box=internal";
  }
  return undefined;
}

export function Component() {
  const location = useLocation();
  const match = matchSection(location.pathname, location.search);
  const moved =
    match?.module.code === "eds"
      ? movedListPath(match.section.key, match.objectId, location.search)
      : undefined;
  if (moved) return <Navigate to={moved} replace />;
  if (match?.module.code === "eds" && match.section.key === "inbox") {
    return (
      <RequireAccess rule={match.section.access}>
        <InboxScreen objectId={match.objectId} />
      </RequireAccess>
    );
  }
  if (match?.module.code === "eds" && match.section.key === "mail") {
    return (
      <RequireAccess rule={match.section.access}>
        <MailScreen objectId={match.objectId} />
      </RequireAccess>
    );
  }
  if (match?.module.code === "eds" && match.section.key === "mymail") {
    return (
      <RequireAccess rule={match.section.access}>
        <MailScreen objectId={match.objectId} own />
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
  if (match?.module.code === "eds" && match.section.key === "projects") {
    return (
      <RequireAccess rule={match.section.access}>
        <ProjectsScreen objectId={match.objectId} />
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
  if (match?.module.code === "eds" && match.section.key === "payments") {
    // Смена реквизитов переехала в «Контакты · Контрагенты»
    if (new URLSearchParams(location.search).get("show") === "bank_changes") {
      return <Navigate to="/crm/clients?kind=bank_changes" replace />;
    }
    return (
      <RequireAccess rule={match.section.access}>
        <PaymentsScreen objectId={match.objectId} />
      </RequireAccess>
    );
  }
  if (match?.module.code === "eds" && match.section.key === "outbox") {
    // Реестр исходящих — «Исходящие»; КП открывается своей карточкой
    const to = match.objectId
      ? `/eds/drafts/${encodeURIComponent(match.objectId)}${location.search}`
      : "/eds/documents?box=outgoing";
    return <Navigate to={to} replace />;
  }
  if (match?.module.code === "eds" && match.section.key === "documents") {
    return (
      <RequireAccess rule={match.section.access}>
        <DocumentsPage />
      </RequireAccess>
    );
  }
  if (match?.module.code === "eds" && match.section.key === "register") {
    return (
      <RequireAccess rule={match.section.access}>
        <RegisterLetterPage />
      </RequireAccess>
    );
  }
  if (match?.module.code === "eds" && match.section.key === "tasks") {
    return (
      <RequireAccess rule={match.section.access}>
        <TasksScreen objectId={match.objectId} />
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
