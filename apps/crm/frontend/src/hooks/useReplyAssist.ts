import { useMutation } from "@tanstack/react-query";
import { useCallback } from "react";

import { assist } from "../api/generated/crm";
import type { AssistOut } from "../api/generated/model";
import { unwrap } from "../api/http";
import type { AssistMode } from "../domain/replyAssist";
import { useApiErrorToast } from "./useApiErrorToast";

export type AssistRunner = {
  /** Текст для поля ответа или `null`, если запрос не удался (тост уже показан). */
  run: (mode: AssistMode, text: string) => Promise<AssistOut | null>;
  /** Какая кнопка сейчас ждёт ответа модели. */
  pending: AssistMode | null;
};

/** ИИ-помощь менеджеру при ответе (Q-019): вызов `POST /leads/{id}/assist`, ошибки — тостом. */
export function useReplyAssist(leadId: number): AssistRunner {
  const onError = useApiErrorToast();
  const mutation = useMutation({
    mutationFn: async ({ mode, text }: { mode: AssistMode; text: string }) =>
      unwrap(await assist(leadId, mode === "improve" ? { mode, text } : { mode })),
  });
  const { mutateAsync } = mutation;
  const run = useCallback(
    async (mode: AssistMode, text: string) => {
      try {
        return await mutateAsync({ mode, text });
      } catch (error) {
        onError(error);
        return null;
      }
    },
    [mutateAsync, onError],
  );
  return { run, pending: mutation.isPending ? mutation.variables.mode : null };
}
