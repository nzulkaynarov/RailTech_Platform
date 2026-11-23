import { useState, type ReactNode } from "react";

import { ApiError } from "../../shared/api/errors";
import { StepUpDialog, type PendingStepUp } from "./StepUpDialog";

/** Отказ сервера «нужен свежий код второго фактора» (ДВ-4б). */
export function isStepUpError(error: unknown): error is ApiError {
  return error instanceof ApiError && error.code === "STEP_UP_REQUIRED";
}

/**
 * Свежий код перед чувствительным действием (ДВ-4б): сервер отказал `STEP_UP_REQUIRED` — окно просит код из приложения,
 * после верного кода действие повторяется само. Фактор ещё не включён — окно ведёт в профиль. Использование:
 * `onError: (error) => ask(error, повтор)`; ошибку `isStepUpError` отдельным сообщением не показывать.
 */
export function useStepUp(): {
  ask: (error: unknown, retry: () => void) => boolean;
  dialog: ReactNode;
} {
  const [pending, setPending] = useState<PendingStepUp | null>(null);
  const ask = (error: unknown, retry: () => void): boolean => {
    if (!isStepUpError(error)) return false;
    setPending({ retry, notEnrolled: error.details["reason"] === "second_factor_not_enrolled" });
    return true;
  };
  const dialog = pending ? (
    <StepUpDialog
      pending={pending}
      onClose={() => {
        setPending(null);
      }}
    />
  ) : null;
  return { ask, dialog };
}
