import { useLocation } from "react-router";

import { RequireAccess } from "../app/RequireAccess";
import { NotFoundPage } from "../app/NotFoundPage";
import { matchSection } from "./registry";
import { SectionStubPage } from "./SectionStubPage";

/**
 * Содержимое маршрутов модуля: раздел по адресу (SPEC-v3 §6.3) → страница под `RequireAccess`. Модуль грузится лениво
 * (`lazy` в router.tsx); реальные экраны фаз P2+ подменят `SectionStubPage` по ключу раздела.
 */
export function ModuleRoutes() {
  const location = useLocation();
  const match = matchSection(location.pathname, location.search);
  if (!match) return <NotFoundPage />;
  return (
    <RequireAccess rule={match.section.access}>
      <SectionStubPage module={match.module} section={match.section} objectId={match.objectId} />
    </RequireAccess>
  );
}
