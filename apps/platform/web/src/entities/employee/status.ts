import type { Employee, EmployeeStatus } from "../../shared/api/generated/model";
import type { StatusTone } from "../../shared/lib/statuses";

/** Статус сотрудника словом и цветом (SPEC-v3 §7.6): активен, приглашён, отключён. */
export const EMPLOYEE_STATUS_TONE: Record<EmployeeStatus, StatusTone> = {
  active: "green",
  invited: "gold",
  disabled: "default",
};

export const EMPLOYEE_STATUSES: readonly EmployeeStatus[] = ["active", "invited", "disabled"];

/** Итог провижининга ERP, о котором стоит сказать словом: «ок» и «не требуется» отдельной метки не получают. */
export function erpAttention(
  employee: Pick<Employee, "access" | "erp_sync">,
): "pending" | "error" | null {
  if (!employee.access.erp) return null;
  return employee.erp_sync === "pending" || employee.erp_sync === "error"
    ? employee.erp_sync
    : null;
}
