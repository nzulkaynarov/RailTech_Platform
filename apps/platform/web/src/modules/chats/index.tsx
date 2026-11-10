import { useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { CalendarPage } from "./calendar/CalendarPage";

/** Маршруты Органайзера: «Календарь» — экран с данными, остальные разделы пока заглушки модуля. */
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
  return <ModuleRoutes />;
}
