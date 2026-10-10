import { App as AntApp } from "antd";
import { useCallback } from "react";
import { useNavigate } from "react-router";

import { type LeadAction, useLeadAction } from "../api/queries";
import { t } from "../i18n/ru";
import { useApiErrorToast } from "./useApiErrorToast";

/** Тост успеха по виду действия: «Лид ваш», «Сделка закрыта»… (аудит UX-copy №12). */
export const doneText = (action: LeadAction): string =>
  t.actions.doneBy[action.kind] ?? t.actions.done;

/**
 * Выполнить действие над лидом: тост с итогом или понятной ошибкой.
 * Возвращает `true`, если действие прошло (диалог можно закрыть).
 */
export function useLeadActionRunner(leadId: number) {
  const { message } = AntApp.useApp();
  const onError = useApiErrorToast();
  const mutation = useLeadAction(leadId);
  const { mutateAsync } = mutation;
  const run = useCallback(
    async (action: LeadAction): Promise<boolean> => {
      try {
        await mutateAsync(action);
        void message.success(doneText(action));
        return true;
      } catch (error) {
        onError(error);
        return false;
      }
    },
    [message, mutateAsync, onError],
  );
  return { run, busy: mutation.isPending };
}

/** «Забрать» из очереди и сразу открыть карточку лида (дизайн-аудит, отчёт 2, шаг 2). */
export function useTakeAndOpen(leadId: number) {
  const navigate = useNavigate();
  const { run, busy } = useLeadActionRunner(leadId);
  const takeAndOpen = useCallback(async () => {
    if (await run({ kind: "take" })) void navigate(`/leads/${String(leadId)}`);
  }, [leadId, navigate, run]);
  return { takeAndOpen, busy };
}
