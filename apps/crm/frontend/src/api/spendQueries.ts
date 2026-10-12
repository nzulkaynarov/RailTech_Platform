/** Запросы «Расходы» и «Модели ИИ» (админ). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { changeModel, getSpend, listModels, resetModel, testModel } from "./generated/crm";
import type { ModelChangeIn } from "./generated/model";
import { unwrap } from "./http";

export const spendKeys = {
  spend: (days: number) => ["spend", days] as const,
  models: ["models"] as const,
};

export const useSpend = (days: number) =>
  useQuery({
    queryKey: spendKeys.spend(days),
    queryFn: async () => unwrap(await getSpend({ days })),
  });

export const useModels = () =>
  useQuery({ queryKey: spendKeys.models, queryFn: async () => unwrap(await listModels()) });

export function useTestModel() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (alias: string) => unwrap(await testModel(alias)),
    // Результат проверки пишется в состояние монитора — обновляем и «Состояние системы».
    onSettled: async () => {
      await client.invalidateQueries({ queryKey: spendKeys.models });
      await client.invalidateQueries({ queryKey: ["system", "status"] });
      await client.invalidateQueries({ queryKey: ["setup", "checklist"] });
    },
  });
}

/** Смена модели роли и сброс к значению по умолчанию (ADR-0020): после — обновить таблицу. */
export function useChangeModel() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (args: { alias: string; body: ModelChangeIn; reset: boolean }) =>
      unwrap(
        args.reset
          ? await resetModel(args.alias, { password: args.body.password })
          : await changeModel(args.alias, args.body),
      ),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: spendKeys.models });
    },
  });
}
