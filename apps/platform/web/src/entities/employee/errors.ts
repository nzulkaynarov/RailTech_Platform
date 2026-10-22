import type { TFunction } from "i18next";

import { ApiError } from "../../shared/api/errors";

/**
 * Текст ошибки операций над сотрудником для сотрудника-админа. Коды — контракт BFF (`LAST_ADMIN`, `EMAIL_EXISTS`);
 * `CONFLICT` с `details.backend_code = user_has_active_leads` — лиды в работе (CRM требует передать их коллеге).
 */
export function employeeErrorText(t: TFunction, error: unknown): string {
  const base = "modules:admin.org.errors.";
  if (!(error instanceof ApiError)) return t(`${base}DEFAULT`);
  if (error.code === "CONFLICT" && error.details["backend_code"] === "user_has_active_leads") {
    return t(`${base}ACTIVE_LEADS`);
  }
  if (
    [
      "LAST_ADMIN",
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
