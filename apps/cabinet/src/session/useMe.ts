import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { logout, type Me } from '@/api/portal';
import { ME_QUERY_KEY, loadSession } from './session';

/** Сессия, контакт, компания и право действовать (`GET /me`). `data === null` — не вошёл. */
export function useMe() {
  return useQuery<Me | null>({
    queryKey: ME_QUERY_KEY,
    queryFn: loadSession,
    staleTime: 5 * 60 * 1000,
    retry: false,
    refetchOnWindowFocus: false,
  });
}

/** `can_act` из `/me`: `false` — только просмотр, кнопки действий скрыты (API всё равно ответит 403). */
export function useCanAct(): boolean {
  return useMe().data?.can_act ?? false;
}

/** Записать сессию, полученную входом (`/auth/telegram`, `/auth/magic/{token}`). */
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
