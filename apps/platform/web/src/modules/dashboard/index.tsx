import { useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { QueuePage } from "./QueuePage";

/** Маршруты Dashboard: «Моя очередь» — экран с данными (PLT-14), остальные разделы пока заглушки модуля. */
export function Component() {
  const location = useLocation();
  const match = matchSection(location.pathname, location.search);
  if (match?.module.code === "dashboard" && match.section.key === "queue") {
    return (
      <RequireAccess rule={match.section.access}>
        <QueuePage />
      </RequireAccess>
    );
  }
  return <ModuleRoutes />;
}
