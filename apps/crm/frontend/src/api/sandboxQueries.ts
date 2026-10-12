/** «Проверить бота» — песочница диалога (админ). Состояние ленты живёт на странице. */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { sandboxMessage, sandboxReset } from "./generated/crm";
import type { SandboxMessageIn } from "./generated/model";
import { unwrap } from "./http";

export function useSandboxSend() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: SandboxMessageIn) => unwrap(await sandboxMessage(body)),
    // Ход бота тратит деньги (тест) — «Расходы» должны показать его без перезагрузки.
    onSettled: async () => {
      await client.invalidateQueries({ queryKey: ["spend"] });
    },
  });
}

export const useSandboxReset = () =>
  useMutation({
    mutationFn: async () => {
      await sandboxReset();
    },
  });
