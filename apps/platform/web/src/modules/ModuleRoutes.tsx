import { useLocation } from "react-router";

import { RequireAccess } from "../app/RequireAccess";
import { NotFoundPage } from "../app/NotFoundPage";
import { matchSection } from "./registry";

/**
 * Запасной маршрут модуля: экраны разделов модуль выбирает сам (`index.tsx`); сюда попадает адрес, для которого экрана нет
 * (например, карточка по номеру в разделе без карточек). Права раздела проверяются, дальше — «Страница не найдена».
 */
export function ModuleRoutes() {
  const location = useLocation();
  const match = matchSection(location.pathname, location.search);
  if (!match) return <NotFoundPage />;
  return (
    <RequireAccess rule={match.section.access}>
      <NotFoundPage />
    </RequireAccess>
  );
}
