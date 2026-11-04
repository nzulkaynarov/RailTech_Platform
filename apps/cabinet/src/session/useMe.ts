import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { logout, type Me } from '@/api/portal';
import { ME_QUERY_KEY, loadSession } from './session';

/** Сессия, контакт, компания и право действовать (`GET /me`). `data === null` — не вошёл. */
export function useMe({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery<Me | null>({
    enabled,
    queryKey: ME_QUERY_KEY,
    queryFn: loadSession,
    staleTime: 5 * 60 * 1000,
    retry: false,
    refetchOnWindowFocus: false,
  });
}

/** `can_act` из `/me`: `false` — только просмотр, кнопки действий скрыты (API всё равно ответит 403). Одинаково у клиента и партнёра. */
export function useCanAct(): boolean {
  return useMe().data?.can_act ?? false;
}

/** Есть ли у сессии модуль кабинета (`/me.modules`). */
export function useHasModule(module: string): boolean {
  return (useMe().data?.modules as readonly string[] | undefined)?.includes(module) ?? false;
}

/** Записать сессию, полученную входом (`/auth/telegram`, `POST /auth/magic`). */
export function useSetSession() {
  const queryClient = useQueryClient();
  return (me: Me | null) => queryClient.setQueryData<Me | null>(ME_QUERY_KEY, me);
}

/** `POST /auth/logout`; данные прошлой сессии стираются из кэша целиком. */
export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: logout,
    onSettled: () => {
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== ME_QUERY_KEY[0] });
      queryClient.setQueryData<Me | null>(ME_QUERY_KEY, null);
    },
  });
}
