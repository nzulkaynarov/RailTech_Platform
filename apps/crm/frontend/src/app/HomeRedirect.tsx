import { Navigate } from "react-router";

import { usePermissionsQuery } from "../api/queries";
import { homePath } from "./navigation";

/** Стартовая страница по правам: менеджер и админ — «Входящие», наблюдатель — дашборд. */
export function HomeRedirect() {
  const { data, isLoading } = usePermissionsQuery();
  if (isLoading) return null;
  return <Navigate to={homePath(data)} replace />;
}
