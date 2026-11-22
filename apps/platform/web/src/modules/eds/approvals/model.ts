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

/**
 * Label of the route step the memo waits at now (EDS marks it `current`; before it is set — the first `pending` one),
 * `null` if the route shows none.
 */
export function currentStepLabel(steps: MemoApprovalCard["steps"]): string | null {
  const step =
    steps.find((s) => s.status === "current") ?? steps.find((s) => s.status === "pending");
  return step ? step.label : null;
}

/**
 * When `meId` (`crm_user_id`) approved this memo in the current round: the fact is the decided route step or a decision of
 * this round, so the card never says «you will be able to decide» to someone who already did.
 */
export function myApprovalAt(memo: MemoApprovalCard, meId: string): string | null {
  const step = memo.steps.find(
    (s) =>
      s.status === "approved" &&
      s.decided_by !== null &&
      String(s.decided_by.crm_user_id) === meId &&
      s.decided_at !== null,
  );
  if (step?.decided_at) return step.decided_at;
  const decision = memo.decisions
    .filter(
      (d) =>
        d.round === memo.round && d.decision === "approve" && String(d.by.crm_user_id) === meId,
    )
    .at(-1);
  return decision ? decision.at : null;
}
