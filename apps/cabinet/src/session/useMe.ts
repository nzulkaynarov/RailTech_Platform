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

/**
 * Может ли сессия действовать: `can_act` из `/me` (`false` — только просмотр, кнопки действий скрыты, API всё равно ответит 403).
 * Партнёр без роли клиента действует в своих разделах («Мои товары», «Каталог и заявки») и без `can_act`: подписывать за
 * компанию ему нечего, КП, договоры и акты ему закрыты модулями (ADR-0022; то же правило у ERP, `portal/permissions.py`).
 */
export function canActIn(me: Me | null | undefined): boolean {
  if (!me) return false;
  return me.can_act || (me.roles.includes('partner') && !me.roles.includes('client'));
}

export function useCanAct(): boolean {
  return canActIn(useMe().data);
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
