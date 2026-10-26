import { ApiError } from "../../shared/api/errors";

/** Код ошибки BFF -> ключ текста `audit:resetPassword.errors.*`. */
export function resetErrorKey(error: unknown): string {
  if (!(error instanceof ApiError)) return "DEFAULT";
  if (error.code === "CONFLICT" && error.details["reason"] === "self_reset") return "SELF_RESET";
  return [
    "NOT_CONFIGURED",
    "SECRETS_KEY_MISSING",
    "FORBIDDEN",
    "NOT_FOUND",
    "BACKEND_UNAVAILABLE",
  ].includes(error.code)
    ? error.code
    : "DEFAULT";
}
