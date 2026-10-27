import { useQueryClient } from "@tanstack/react-query";

import {
  getListEmployeesQueryKey,
  useCreateEmployee,
  useIssueTemporaryPassword,
} from "../../shared/api/generated/platform-bff";
import { getGetSetupChecklistQueryKey } from "../../shared/api/generated/platform-bff";

/**
 * Мутации с временным паролем в ответе. `gcTime: 0` — запись мутации (а с ней и пароль) удаляется из кэша запросов, как
 * только на неё никто не смотрит; экран забирает пароль в своё состояние и вызывает `reset()`. После создания список
 * сотрудников и чек-лист («первый сотрудник») перечитываются.
 */
export function useCreateEmployeeWithPassword() {
  const queryClient = useQueryClient();
  return useCreateEmployee({
    mutation: {
      gcTime: 0,
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: getListEmployeesQueryKey() });
        void queryClient.invalidateQueries({ queryKey: getGetSetupChecklistQueryKey() });
      },
    },
  });
}

export function useIssueTemporaryPasswordAction() {
  const queryClient = useQueryClient();
  return useIssueTemporaryPassword({
    mutation: {
      gcTime: 0,
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: getListEmployeesQueryKey() });
      },
    },
  });
}
