/** «Проверить бота» — песочница диалога (админ). Состояние ленты живёт на странице. */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { getGetSpendQueryKey, sandboxMessage } from "./generated/crm";
import type { SandboxMessageIn } from "./generated/model";

export { useSandboxReset } from "./generated/crm";

export function useSandboxSend() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: SandboxMessageIn) => sandboxMessage(body),
    // Ход бота тратит деньги (тест) — «Расходы» должны показать его без перезагрузки.
    onSettled: () => client.invalidateQueries({ queryKey: getGetSpendQueryKey() }),
  });
}
