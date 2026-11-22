import { useTranslation } from "react-i18next";

import { useAuth } from "../../../app/auth/useAuth";
import type { MemoApprovalCard } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { currentStepLabel, myApprovalAt } from "./model";

/**
 * «Сейчас шаг: …» for someone who may decide memos but is not at the step now; «Вы согласовали …» when they already approved
 * in this round. `null` if the route names no current step (the caller keeps its generic text).
 */
export function useStepNote(memo: MemoApprovalCard): string | null {
  const { t } = useTranslation("approvals");
  const { me } = useAuth();
  const { date } = useFormat();
  const label = currentStepLabel(memo.steps);
  if (!label) return null;
  const approvedAt = myApprovalAt(memo, me.id);
  return approvedAt
    ? t("panel.readOnly.decidedStep", { date: date(approvedAt), label })
    : t("panel.readOnly.notYourStep", { label });
}
