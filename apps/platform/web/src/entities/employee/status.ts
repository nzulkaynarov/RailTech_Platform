import type { Employee, EmployeeStatus } from "../../shared/api/generated/model";

/** Хоть у кого-то доступ в ERP ещё выдаётся: список перечитывается, пока ERP не ответит. */
export function anyErpPending(items: readonly Employee[] | undefined): boolean {
  return (items ?? []).some((employee) => erpAttention(employee) === "pending");
}

export const EMPLOYEE_STATUSES: readonly EmployeeStatus[] = ["active", "invited", "disabled"];

/** Итог провижининга ERP, о котором стоит сказать словом: «ок» и «не требуется» отдельной метки не получают.
 *  У отключённого про выдачу доступа — ничего: отзыв сессий не «выдаётся» (СЦ-8). */
export function erpAttention(
  employee: Pick<Employee, "access" | "erp_sync" | "status">,
): "pending" | "error" | null {
  if (!employee.access.erp || employee.status === "disabled") return null;
  return employee.erp_sync === "pending" || employee.erp_sync === "error"
    ? employee.erp_sync
    : null;
}

export type ErpSyncReason = "not_configured" | "unavailable" | "rejected";

/** Python/httpx exception names CRM writes as the "code" of a transient failure (`ConnectError`, `ReadTimeout`, …). */
const TRANSIENT_CODE = /^[A-Z][A-Za-z]*(Error|Exception|Timeout)$/;

/**
 * Human reason of a failed ERP provisioning from `erp_sync_error` (CRM writes `task: code: detail`, 500 chars max).
 * The text itself is never shown: the code decides the sentence. `null` — CRM has no error text ("не выдан", no job).
 */
export function erpSyncReason(error: string | undefined | null): ErpSyncReason | null {
  if (!error) return null;
  const code = error.split(": ")[1]?.trim() ?? "";
  if (code === "erp_not_configured") return "not_configured";
  if (TRANSIENT_CODE.test(code)) return "unavailable";
  return "rejected";
}
