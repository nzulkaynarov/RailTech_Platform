import type { TFunction } from "i18next";

/** Причина недоставки письма словами; неизвестный код — общая формулировка. */
export function bounceReason(t: TFunction, reason: string): string {
  return t(`ui:emailProblem.reasons.${reason}`, {
    defaultValue: t("ui:emailProblem.reasons.other"),
  });
}
