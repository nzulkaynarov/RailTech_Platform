import { useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { CalendarPage } from "./calendar/CalendarPage";
import { ChatsPage } from "./inbox/ChatsPage";
import { PeoplePage } from "./people/PeoplePage";

/** Маршруты Органайзера: «Календарь», «Чаты» и «Люди» — настоящие экраны, остальные разделы пока заглушки модуля. */
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
  if (match?.module.code === "chats" && match.section.key === "contacts") {
    return (
      <RequireAccess rule={match.section.access}>
        <PeoplePage />
      </RequireAccess>
    );
  }
  return <ModuleRoutes />;
}
