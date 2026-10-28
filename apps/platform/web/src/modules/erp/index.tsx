import { useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { CalcScreen } from "./calc/CalcScreen";
import { RequestsScreen } from "./calc/RequestsScreen";

/**
 * Модуль «Расчёт» (ERP). «Заявки в расчёте» и «Мои расчёты» — список заданий на расчёт, карточка `/erp/calc/ЗВ-…` (и
 * `/erp/requests/ЗВ-…`) — расчёт по заявке (D2-1, SPEC-v3 §7.4); склад, номенклатура и техдокументация — заглушки каркаса
 * до D2-2 и D2-3.
 */
export function Component() {
  const location = useLocation();
  const match = matchSection(location.pathname, location.search);
  if (
    match?.module.code === "erp" &&
    (match.section.key === "requests" || match.section.key === "calc")
  ) {
    return (
      <RequireAccess rule={match.section.access}>
        {match.objectId ? (
          <CalcScreen number={match.objectId} />
        ) : (
          <RequestsScreen mine={match.section.key === "calc"} />
        )}
      </RequireAccess>
    );
  }
  return <ModuleRoutes />;
}
