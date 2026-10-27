import type { MemoApprovalCard } from "../../../shared/api/generated/model";

/** Следующий шаг маршрута после текущего («Бухгалтер»), если документ идёт дальше. */
export function nextStepLabel(steps: MemoApprovalCard["steps"]): string | null {
  const current = steps.findIndex((s) => s.status === "current");
  if (current < 0) return null;
  const next = steps.slice(current + 1).find((s) => s.status === "pending");
  return next ? next.label : null;
}
