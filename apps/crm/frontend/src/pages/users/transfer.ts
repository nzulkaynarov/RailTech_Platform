/**
 * Передача работы уходящего сотрудника (ADR-0015, SPEC §10.1): снятие роли менеджера или
 * деактивацию того, кто ведёт лидов, бэкенд отклоняет с `user_has_active_leads` или требует
 * `transfer_to_user_id` — диалог показывает выбор коллеги и отправляет изменение ещё раз.
 */
import { ApiError } from "../../api/http";

/** Сколько лидов нужно передать (0 — число неизвестно) или `null`, если ошибка о другом. */
export function transferNeeded(error: unknown): number | null {
  if (!(error instanceof ApiError)) return null;
  const transferField = error.details["field"] === "transfer_to_user_id";
  if (error.code !== "user_has_active_leads" && !transferField) return null;
  const count = error.details["count"];
  return typeof count === "number" ? count : 0;
}
