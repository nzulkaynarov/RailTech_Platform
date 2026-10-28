import { useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { CalcScreen } from "./calc/CalcScreen";
import { RequestsScreen } from "./calc/RequestsScreen";
import { CatalogScreen } from "./catalog/CatalogScreen";
import { DocsScreen } from "./docs/DocsScreen";
import { OrderScreen } from "./stock/OrderScreen";
import { StockScreen } from "./stock/StockScreen";

/**
 * Модуль «Расчёт» (ERP). «Заявки в расчёте» и «Мои расчёты» — список заданий на расчёт, карточка `/erp/calc/ЗВ-…` (и
 * `/erp/requests/ЗВ-…`) — расчёт по заявке (D2-1, SPEC-v3 §7.4); «Склад» (остатки и резервы, заказы поставщикам, приёмка,
 * отгрузки; D2-2) — `/erp/stock`, карточка заказа `/erp/stock/ЗП-…`; «Номенклатура и поставщики» и «Техдокументация» (D2-3).
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
  if (match?.module.code === "erp" && match.section.key === "stock") {
    return (
      <RequireAccess rule={match.section.access}>
        {match.objectId ? <OrderScreen number={match.objectId} /> : <StockScreen />}
      </RequireAccess>
    );
  }
  if (match?.module.code === "erp" && match.section.key === "catalog") {
    return (
      <RequireAccess rule={match.section.access}>
        <CatalogScreen />
      </RequireAccess>
    );
  }
  if (match?.module.code === "erp" && match.section.key === "docs") {
    return (
      <RequireAccess rule={match.section.access}>
        <DocsScreen />
      </RequireAccess>
    );
  }
  return <ModuleRoutes />;
}
