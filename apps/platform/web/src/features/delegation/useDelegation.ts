import { useQueryClient } from "@tanstack/react-query";

import {
  getGetEmployeeDelegationQueryKey,
  getGetMeQueryKey,
  getListEmployeesQueryKey,
  useSetEmployeeDelegation,
} from "../../shared/api/generated/platform-bff";

/** Сохранение «Что делегировано»: после ответа перечитываются набор, список сотрудников и (для себя) профиль. */
export function useSaveDelegation(employeeId: string, selfId: string, onSaved: () => void) {
  const queryClient = useQueryClient();
  return useSetEmployeeDelegation({
    mutation: {
      onSuccess: (next) => {
        queryClient.setQueryData(getGetEmployeeDelegationQueryKey(employeeId), next);
        void queryClient.invalidateQueries({ queryKey: getListEmployeesQueryKey() });
        if (employeeId === selfId)
          void queryClient.invalidateQueries({ queryKey: getGetMeQueryKey() });
        onSaved();
      },
    },
  });
}
