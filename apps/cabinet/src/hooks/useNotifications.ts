import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query';

import * as portal from '@/api/portal';
import { ME_QUERY_KEY, loadSession } from '@/session/session';
import { useMe } from '@/session/useMe';

/** Лента колокольчика: страницы по убыванию `id`, следующая — `before_id` последнего элемента. */
export const NOTIFICATIONS_KEY = ['notifications'] as const;
export const NOTIFICATIONS_PAGE_SIZE = 20;
/** Опрос счётчика (`/me`) — раз в минуту и только при видимой вкладке; ленту отдельно не опрашиваем. */
export const COUNTER_POLL_MS = 60_000;

type Feed = InfiniteData<portal.NotificationPage, number | undefined>;

/** Непрочитанные уведомления контакта (`/me.notifications_unread`), без лишнего запроса. */
export function useNotificationsUnread(): number {
  return useMe().data?.notifications_unread ?? 0;
}

/**
 * Опрос счётчика колокольчика: тот же ключ `/me`, интервал — только пока вкладка видима (`refetchIntervalInBackground:
 * false` — React Query сам ставит опрос на паузу по `visibilitychange`). Ленту опрос не трогает: она грузится при открытии.
 */
export function useNotificationsCounterPolling(): void {
  useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: loadSession,
    staleTime: 5 * 60 * 1000,
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: COUNTER_POLL_MS,
    refetchIntervalInBackground: false,
  });
}

/** Лента — только пока панель открыта; при каждом открытии — свежая первая страница. */
export function useNotificationsFeed(open: boolean) {
  return useInfiniteQuery({
    queryKey: NOTIFICATIONS_KEY,
    queryFn: ({ pageParam }) =>
      portal.listNotifications({ limit: NOTIFICATIONS_PAGE_SIZE, ...(pageParam ? { before_id: pageParam } : {}) }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => (last.has_more ? last.items[last.items.length - 1]?.id : undefined),
    enabled: open,
    staleTime: 0,
  });
}

/** Отметить прочитанным (одно или все): лента и бейдж обновляются ответом ERP без перезапроса. */
export function useMarkNotificationsRead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: portal.markNotificationsRead,
    onSuccess: ({ unread }, body) => {
      const readAt = new Date().toISOString();
      const ids = 'ids' in body && body.ids ? new Set(body.ids) : null;
      client.setQueryData<Feed>(NOTIFICATIONS_KEY, (feed) =>
        feed
          ? {
              ...feed,
              pages: feed.pages.map((page) => ({
                ...page,
                items: page.items.map((item) =>
                  item.read_at === null && (ids === null || ids.has(item.id)) ? { ...item, read_at: readAt } : item,
                ),
              })),
            }
          : feed,
      );
      client.setQueryData<portal.Me | null>(ME_QUERY_KEY, (me) => (me ? { ...me, notifications_unread: unread } : me));
    },
  });
}
