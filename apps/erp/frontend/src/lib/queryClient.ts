import { QueryClient, MutationCache, QueryCache, focusManager, type Query } from '@tanstack/react-query';
import { toast } from 'sonner';

import { translateApiError } from './apiError';

/**
 * Одно место для всех одновременных отказов чтения. Sonner заменяет тост с тем же `id`
 * вместо того, чтобы копить стопку, поэтому страница с десятком запросов при обрыве сети
 * скажет об этом ОДИН раз, а не десять.
 */
const QUERY_ERROR_TOAST_ID = 'query-load-error';

/**
 * «Живые» данные — списки и карточки, которые коллеги меняют параллельно (сделки, КП, договоры,
 * счета, акты, поставки…). Справочники (валюты, единицы, категории, настройки) держат `staleTime`
 * от 5 минут — их при возврате на вкладку не дёргаем. Отличаем по `staleTime` наблюдателей, а не
 * по списку ключей: новый хук с обычным `staleTime` автоматически попадает в живые.
 */
const LIVE_MAX_STALE_MS = 5 * 60_000;

export function isLiveQuery(query: Pick<Query, 'observers'>): boolean {
  return query.observers.some((observer) => {
    const staleTime = observer.options.staleTime;
    return typeof staleTime !== 'number' || staleTime < LIVE_MAX_STALE_MS;
  });
}

// Возврат на вкладку и фокус окна оба считаются «пользователь вернулся» (FIX-58, D-09). Штатный
// слушатель React Query знает только `visibilitychange`: переключение между окнами при видимой
// вкладке ничего не обновляло. Опроса по таймеру нет — только действие человека.
if (typeof window !== 'undefined') {
  focusManager.setEventListener((handleFocus) => {
    const onReturn = () => handleFocus();
    window.addEventListener('visibilitychange', onReturn, false);
    window.addEventListener('focus', onReturn, false);
    return () => {
      window.removeEventListener('visibilitychange', onReturn);
      window.removeEventListener('focus', onReturn);
    };
  });
}

/**
 * The single app-wide React Query client.
 *
 * Exported as a module singleton (not created inline in main.tsx) so auth flows
 * can wipe it on identity change: on a SHARED browser, logging out then logging
 * in as a different user MUST NOT serve the previous user's cached rows. With
 * refetchOnMount:false + staleTime 2m + gcTime 10m, a fresh mount would otherwise
 * read the prior tenant's ['deals']/['quotes']/analytics cache with no network
 * request — a cross-tenant leak. authStore.login/logout call `queryClient.clear()`.
 */
export const queryClient = new QueryClient({
  // Single source of truth for mutation errors: any mutation that does not opt out
  // surfaces a localised toast. Prevents the "action silently failed" class of bugs.
  // A mutation can opt out with meta: { skipErrorToast: true } when it shows its own UI.
  mutationCache: new MutationCache({
    onError: (error, _vars, _ctx, mutation) => {
      if (mutation.meta?.skipErrorToast) return;
      toast.error(translateApiError(error));
    },
  }),
  // Симметрично мутациям — единый источник правды об ошибках ЧТЕНИЯ. Аудит UI 2026-07-30
  // нашёл ~35 мест, где упавший запрос выглядел как «данных нет»: выпадающие списки валют,
  // единиц, категорий и базисов поставки становились пустыми молча, и пользователь не мог
  // заполнить форму, не понимая почему. Поверхность, которая ВЛАДЕЕТ решением (дашборд,
  // список), обязана показать ошибку у себя — тост её не заменяет; но там, где показывать
  // ошибку негде (справочник внутри селекта, фоновой опрос), молчание было единственным
  // исходом. Запрос отказывается от тоста через meta: { skipErrorToast: true }.
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (query.meta?.skipErrorToast) return;
      // 401 — это истёкшая сессия: её отрабатывает интерцептор axios (refresh либо выход).
      // Тост здесь только пугал бы пользователя в момент штатного продления токена.
      const status = (error as { response?: { status?: number } })?.response?.status;
      if (status === 401) return;
      toast.error(translateApiError(error), { id: QUERY_ERROR_TOAST_ID });
    },
  }),
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        // Don't retry 4xx client errors (auth, not-found, etc) — they won't succeed
        const status = (error as { response?: { status?: number } })?.response?.status;
        if (status && status >= 400 && status < 500) return false;
        return failureCount < 1;
      },
      // Живые данные перечитываются при возврате на вкладку ВСЕГДА (в том числе «свежие» по staleTime):
      // иначе коллега утвердил КП, а у автора ещё две минуты нет «Отправить КП» (D-09, FIX-58).
      refetchOnWindowFocus: (query: Query) => (isLiveQuery(query) ? 'always' : false),
      refetchOnReconnect: false,
      refetchOnMount: false,
      staleTime: 2 * 60_000,
      gcTime: 10 * 60_000,
    },
  },
});
