import { Navigate } from "react-router";

import { homePath } from "./access";
import { useAuth } from "./auth/useAuth";

/** Корень Платформы — «домой» по ролям сотрудника (у роли без Dashboard — её первый раздел). */
export function HomeRedirect() {
  const { me } = useAuth();
  return <Navigate to={homePath(me)} replace />;
}
