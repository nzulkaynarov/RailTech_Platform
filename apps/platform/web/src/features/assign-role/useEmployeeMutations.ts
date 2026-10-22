import { useQueryClient } from "@tanstack/react-query";

import {
  getGetMeQueryKey,
  getGetSessionQueryKey,
  getListEmployeesQueryKey,
  useInviteEmployee,
  useUpdateEmployee,
} from "../../shared/api/generated/platform-bff";
import type { Employee, EmployeeList } from "../../shared/api/generated/model";

/**
 * Изменение сотрудника: ответ BFF сразу кладётся в список (карточка и таблица не ждут повторного запроса), список всё
 * равно перечитывается — источник истины CRM. Свои роли поменяли — перечитываем профиль: меню и модули зависят от них.
 */
export function useEmployeeUpdate(selfId: string, onSaved?: (employee: Employee) => void) {
  const queryClient = useQueryClient();
  return useUpdateEmployee({
    mutation: {
      onSuccess: (employee) => {
        queryClient.setQueryData<EmployeeList>(getListEmployeesQueryKey(), (list) =>
          list
            ? {
                ...list,
                items: list.items.map((item) => (item.id === employee.id ? employee : item)),
              }
            : list,
        );
        void queryClient.invalidateQueries({ queryKey: getListEmployeesQueryKey() });
        if (employee.id === selfId) {
          void queryClient.invalidateQueries({ queryKey: getGetMeQueryKey() });
          void queryClient.invalidateQueries({ queryKey: getGetSessionQueryKey() });
        }
        onSaved?.(employee);
      },
    },
  });
}

export function useEmployeeInvite(onInvited?: (employee: Employee) => void) {
  const queryClient = useQueryClient();
  return useInviteEmployee({
    mutation: {
      onSuccess: (employee) => {
        void queryClient.invalidateQueries({ queryKey: getListEmployeesQueryKey() });
        onInvited?.(employee);
      },
      // Письмо не ушло, но сотрудник уже создан: список должен его показать.
      onError: () => {
        void queryClient.invalidateQueries({ queryKey: getListEmployeesQueryKey() });
      },
    },
  });
}
