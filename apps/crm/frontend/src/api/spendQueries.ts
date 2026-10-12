/** Запросы «Расходы» и «Модели ИИ» (админ). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getSpend, listModels, testModel } from "./generated/crm";
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
