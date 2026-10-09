import { useCan } from "@refinedev/core";
import { Navigate } from "react-router";

/** Стартовая страница по правам: очередь работы, а наблюдателю — список лидов. */
export function HomeRedirect() {
  const { data, isLoading } = useCan({ resource: "inbox", action: "list" });
  if (isLoading) return null;
  return <Navigate to={data?.can ? "/inbox" : "/leads"} replace />;
}
