import { Navigate, Outlet, useLocation } from "react-router";

import { legacyPath } from "../modules/legacyRedirects";

/** Старые адреса разделов уводятся на новые до выбора экрана, без лишней записи в историю (ЕВ-3б). */
export function LegacyGate() {
  const location = useLocation();
  const target = legacyPath(location.pathname, location.search);
  if (target !== undefined) return <Navigate to={target} replace />;
  return <Outlet />;
}
