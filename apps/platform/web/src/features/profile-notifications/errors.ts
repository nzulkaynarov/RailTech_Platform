import { ApiError } from "../../shared/api/errors";

/** Ключ текста `audit:profile.errors.*` по ответу BFF на тестовое уведомление. */
export function testErrorKey(error: unknown): string {
  if (!(error instanceof ApiError)) return "DEFAULT";
  const reason = error.details["reason"];
  if (error.code === "NOT_CONFIGURED") return "NOT_CONFIGURED";
  if (error.code === "CONFLICT" && reason === "telegram_not_linked") return "NOT_LINKED";
  if (error.code === "CONFLICT" && reason === "telegram_refused") return "REFUSED";
  return error.code === "BACKEND_UNAVAILABLE" ? "BACKEND_UNAVAILABLE" : "DEFAULT";
}
