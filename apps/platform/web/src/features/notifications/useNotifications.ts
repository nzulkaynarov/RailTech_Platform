import { useQueryClient } from "@tanstack/react-query";

import {
  getListNotificationsQueryKey,
  useListNotifications,
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
} from "../../shared/api/generated/platform-bff";
import type { NotificationPage } from "../../shared/api/generated/model";
import { pollQuery } from "../../shared/api/polling";
import { canSee } from "../../app/access";
import { useAuth } from "../../app/auth/useAuth";

/** Одна страница на все места показа (колокольчик, popover, боковое окно): один запрос, один счётчик непрочитанных. */
export const NOTIFICATION_PARAMS = { limit: 50 } as const;

/**
 * Уведомления открыты разделом «Моя очередь» (BFF: `require("dashboard.queue")`): у роли без него (ADR-0012 — например,
 * «Менеджер и бухгалтер» без Dashboard) запрос не уходит, колокольчик пуст, ошибки «Нет доступа» на экране нет.
 */
export function useNotifications() {
  const { me } = useAuth();
  const enabled = canSee(me, { resource: "dashboard.queue" });
  const query = useListNotifications(NOTIFICATION_PARAMS, { query: { ...pollQuery, enabled } });
  return { query, enabled };
}

type Context = { previous: NotificationPage | undefined };

/** Отметка «прочитано» и «прочитаны все»: сразу в кэше (оптимистично), затем сверка с сервером. */
export function useReadNotifications() {
  const client = useQueryClient();
  const queryKey = getListNotificationsQueryKey(NOTIFICATION_PARAMS);

  const apply = async (change: (page: NotificationPage) => NotificationPage): Promise<Context> => {
    await client.cancelQueries({ queryKey });
    const previous = client.getQueryData<NotificationPage>(queryKey);
    if (previous) client.setQueryData<NotificationPage>(queryKey, change(previous));
    return { previous };
  };
  const rollback = (_error: unknown, _vars: unknown, context: Context | undefined) => {
    if (context?.previous) client.setQueryData(queryKey, context.previous);
  };
  const settle = () => client.invalidateQueries({ queryKey });

  const one = useMarkNotificationRead<Error, Context>({
    mutation: {
      onMutate: ({ id }) =>
        apply((page) => {
          const target = page.items.find((n) => n.id === id);
          if (!target || target.read) return page;
          return {
            ...page,
            unread_count: Math.max(page.unread_count - 1, 0),
            items: page.items.map((n) => (n.id === id ? { ...n, read: true } : n)),
          };
        }),
      onError: rollback,
      onSettled: settle,
    },
  });
  const all = useMarkAllNotificationsRead<Error, Context>({
    mutation: {
      onMutate: () =>
        apply((page) => ({
          ...page,
          unread_count: 0,
          items: page.items.map((n) => ({ ...n, read: true })),
        })),
      onError: rollback,
      onSettled: settle,
    },
  });
  return {
    markRead: (id: string) => {
      one.mutate({ id });
    },
    markAll: () => {
      all.mutate(undefined);
    },
    markAllPending: all.isPending,
  };
}
