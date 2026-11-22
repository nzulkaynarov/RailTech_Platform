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
