import { canEdit } from "../../../app/access";
import type { Me, MemoApprovalCard } from "../../../shared/api/generated/model";

/** Следующий шаг маршрута после текущего («Бухгалтер»), если документ идёт дальше. */
export function nextStepLabel(steps: MemoApprovalCard["steps"]): string | null {
  const current = steps.findIndex((s) => s.status === "current");
  if (current < 0) return null;
  const next = steps.slice(current + 1).find((s) => s.status === "pending");
  return next ? next.label : null;
}

/**
 * Решать документы на согласовании может директор (`eds.memo.approve`) и бухгалтер на своём шаге (`eds.payments`, «Принять к
 * оплате»). Чей сейчас шаг, знает EDS (`can_decide`): раздел только открывает кнопки.
 */
export function mayDecideMemos(me: Me): boolean {
  return canEdit(me, "eds.memo.approve") || canEdit(me, "eds.payments");
}
