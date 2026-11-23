import { Suspense, lazy } from "react";
import { useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { QueuePage } from "./QueuePage";

// График тяжёлый: его код загружается только на «Сводке», а не на главном экране.
const SummaryPage = lazy(() =>
  import("./SummaryPage").then((module) => ({ default: module.SummaryPage })),
);

/** Маршруты Главной: «Задачи» и «Сводка» — экраны с данными, остальные разделы пока заглушки модуля. */
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
  if (match?.module.code === "dashboard" && match.section.key === "summary") {
    return (
      <RequireAccess rule={match.section.access}>
        <Suspense fallback={null}>
          <SummaryPage />
        </Suspense>
      </RequireAccess>
    );
  }
  return <ModuleRoutes />;
}
