import type { TFunction } from "i18next";

import { ApiError } from "../../../shared/api/errors";

/** Текст ошибки операций с ролью: коды контракта BFF 0.3.0 (`ROLE_IN_USE`, `ROLE_SYSTEM`, `LAST_ADMIN`, `CONFLICT`). */
export function roleErrorText(t: TFunction, error: unknown): string {
  if (!(error instanceof ApiError)) return t("admin.roles.errors.DEFAULT");
  if (error.code === "ROLE_IN_USE") {
    const count = Number(error.details["employees"] ?? 0);
    return t("admin.roles.errors.ROLE_IN_USE", { count });
  }
  if (error.code === "CONFLICT" && error.details["reason"] === "name_taken") {
    return t("admin.roles.errors.NAME_TAKEN");
  }
  if (
    ["ROLE_SYSTEM", "LAST_ADMIN", "FORBIDDEN", "BACKEND_UNAVAILABLE", "VALIDATION_FAILED"].includes(
      error.code,
    )
  ) {
    return t(`admin.roles.errors.${error.code}`);
  }
  return t("admin.roles.errors.DEFAULT");
}
