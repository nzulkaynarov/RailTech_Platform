import { useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { CalendarPage } from "./calendar/CalendarPage";
import { ChatsPage } from "./inbox/ChatsPage";

/** Маршруты Органайзера: «Календарь» и «Чаты» — настоящие экраны, остальные разделы пока заглушки модуля. */
export function Component() {
  const location = useLocation();
  const match = matchSection(location.pathname, location.search);
  if (match?.module.code === "chats" && match.section.key === "calendar") {
    return (
      <RequireAccess rule={match.section.access}>
        <CalendarPage />
      </RequireAccess>
    );
  }
  if (match?.module.code === "chats" && match.section.key === "all" && !match.objectId) {
    return (
      <RequireAccess rule={match.section.access}>
        <ChatsPage />
      </RequireAccess>
    );
  }
  return <ModuleRoutes />;
}
