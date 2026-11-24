import { useTranslation } from "react-i18next";

import type { EmailProblem as EmailProblemModel } from "../api/generated/model";
import { bounceReason } from "../lib/bounceReason";
import { useFormat } from "../lib/useFormat";

/**
 * «Письма на этот адрес не доходят: причина · дата» (отчёты о недоставке, CRM mb1). Автоматические письма на адрес не
 * уходят, пока его не исправят; само письмо-отчёт остаётся в журнале почты, а не среди обращений.
 */
export function EmailProblem({ problem }: { problem: EmailProblemModel | null | undefined }) {
  const { t } = useTranslation("ui");
  const fmt = useFormat();
  if (!problem) return null;
  return (
    <span className="pf-req-error" role="note">
      {t("emailProblem.line", {
        title: t("emailProblem.title"),
        reason: bounceReason(t, problem.reason),
        date: fmt.date(problem.at),
      })}
    </span>
  );
}
