import type { TFunction } from "i18next";

import { ApiError } from "../../shared/api/errors";

/**
 * Текст ошибки операций над сотрудником для сотрудника-админа. Коды — контракт BFF (`LAST_ADMIN`, `LAST_DIRECTOR`,
 * `EMAIL_EXISTS`, `ROLES_REQUIRED` — пустой набор ролей, 0.6.0); `CONFLICT` с `details.reason = user_has_active_leads` — лиды
 * в работе (CRM требует передать их коллеге).
 */
export function employeeErrorText(t: TFunction, error: unknown): string {
  const base = "modules:admin.org.errors.";
  if (!(error instanceof ApiError)) return t(`${base}DEFAULT`);
  const reason = error.details["reason"] ?? error.details["backend_code"];
  if (error.code === "CONFLICT" && reason === "user_has_active_leads") {
    return t(`${base}ACTIVE_LEADS`);
  }
  if (error.code === "CONFLICT" && reason === "own_account") return t(`${base}OWN_ACCOUNT`);
  if (
    [
      "LAST_ADMIN",
      "LAST_DIRECTOR",
      "ROLES_REQUIRED",
      "EMAIL_EXISTS",
      "FORBIDDEN",
      "BACKEND_UNAVAILABLE",
      "VALIDATION_FAILED",
    ].includes(error.code)
  ) {
    return t(`${base}${error.code}`);
  }
  return t(`${base}DEFAULT`);
}
