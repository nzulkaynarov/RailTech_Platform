import { ApiError } from "../../shared/api/errors";

/** Ответ CRM «у сотрудника лиды в работе» (409 `CONFLICT`, `details.reason = user_has_active_leads`). */
export function hasActiveLeads(error: unknown): boolean {
  if (!(error instanceof ApiError) || error.code !== "CONFLICT") return false;
  const reason = error.details["reason"] ?? error.details["backend_code"];
  return reason === "user_has_active_leads";
}
