import { Navigate, useLocation } from "react-router";

import { RequireAccess } from "../../app/RequireAccess";
import { ModuleRoutes } from "../ModuleRoutes";
import { matchSection } from "../registry";
import { CalcScreen } from "./calc/CalcScreen";
import { RequestsScreen } from "./calc/RequestsScreen";
import { CatalogScreen } from "./catalog/CatalogScreen";
import { DocsScreen } from "./docs/DocsScreen";
import { OrderCreatePage } from "./stock/OrderCreatePage";
import { OrderScreen } from "./stock/OrderScreen";
import { StockScreen } from "./stock/StockScreen";

/**
 * Модуль «Расчёт» (ERP). «Заявки в расчёте» и «Мои расчёты» — список заданий на расчёт, карточка `/erp/calc/ЗВ-…` (и
 * `/erp/requests/ЗВ-…`) — расчёт по заявке (D2-1, SPEC-v3 §7.4); «Склад» (остатки и резервы, заказы поставщикам, приёмка,
 * отгрузки; D2-2) — `/erp/stock`, карточка заказа `/erp/stock/ЗП-…`; «Номенклатура и поставщики» и «Техдокументация» (D2-3).
 */
/** Партнёры и заявки на подключение переехали в «Контакты · Контрагенты»: старые адреса каталога ведут туда. */
function movedPartnerPath(search: string): string | undefined {
  const params = new URLSearchParams(search);
  const part = params.get("part");
  if (part === "applications") return "/crm/clients?kind=applications";
  if (part !== "suppliers") return undefined;
  const id = params.get("supplier");
  return id
    ? `/crm/clients?partner=${encodeURIComponent(id)}&panel=open&tab=card`
    : "/crm/clients?kind=partners";
}

export function Component() {
  const location = useLocation();
  const match = matchSection(location.pathname, location.search);
  if (
    match?.module.code === "erp" &&
    (match.section.key === "requests" || match.section.key === "calc")
  ) {
    // «Мои расчёты» стали фильтром списка заявок; карточка расчёта остаётся по своему адресу
    if (match.section.key === "calc" && !match.objectId) {
      return <Navigate to="/erp/requests?mine=1" replace />;
    }
    return (
      <RequireAccess rule={match.section.access}>
        {match.objectId ? <CalcScreen number={match.objectId} /> : <RequestsScreen />}
      </RequireAccess>
    );
  }
  if (match?.module.code === "erp" && match.section.key === "stock") {
    return (
      <RequireAccess rule={match.section.access}>
        {match.objectId === "new" ? (
          <OrderCreatePage />
        ) : match.objectId ? (
          <OrderScreen number={match.objectId} />
        ) : (
          <StockScreen />
        )}
      </RequireAccess>
    );
  }
  if (match?.module.code === "erp" && match.section.key === "catalog") {
    const moved = movedPartnerPath(location.search);
    if (moved) return <Navigate to={moved} replace />;
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
