/** Запросы «Расходы» и «Модели ИИ» (админ). */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  changeModel,
  getGetSetupChecklistQueryKey,
  getListModelsQueryKey,
  getSystemStatusQueryKey,
  resetModel,
  testModel,
  useGetAiSpend,
  useGetSpend,
  useListModels,
} from "./generated/crm";
import type { GetAiSpendGroup, ModelChangeIn } from "./generated/model";

export const useSpend = (days: number) => useGetSpend({ days });

/** «Расходы» по ансамблю (M3-CRM-09): журнал LiteLLM за период, ряды по `group`. */
export const useAiSpend = (range: { from: string; to: string }, group: GetAiSpendGroup) =>
  useGetAiSpend({ ...range, group });

export const useModels = () => useListModels();

export function useTestModel() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (alias: string) => testModel(alias),
    // Результат проверки пишется в состояние монитора — обновляем и «Состояние системы».
    onSettled: () =>
      Promise.all(
        [getListModelsQueryKey(), getSystemStatusQueryKey(), getGetSetupChecklistQueryKey()].map(
          (queryKey) => client.invalidateQueries({ queryKey }),
        ),
      ),
  });
}

/** Смена модели роли и сброс к значению по умолчанию (ADR-0020): после — обновить таблицу. */
export function useChangeModel() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (args: { alias: string; body: ModelChangeIn; reset: boolean }) =>
      args.reset
        ? resetModel(args.alias, { password: args.body.password })
        : changeModel(args.alias, args.body),
    onSuccess: () => client.invalidateQueries({ queryKey: getListModelsQueryKey() }),
  });
}
