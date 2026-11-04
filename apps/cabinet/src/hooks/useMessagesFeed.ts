import { useCallback, useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import * as portal from '@/api/portal';
import { keys } from '@/api/queries';
import {
  MAX_CATCH_UP_PAGES,
  POLL_INTERVAL_MS,
  lastManagerId,
  lastMessageId,
  mergeMessages,
  newClientMessageId,
  unsentPending,
  type PendingMessage,
} from '@/lib/messages';
import { ME_QUERY_KEY } from '@/session/session';

/**
 * Лента чата кабинета (CHAT-1, ADR-0023): первая страница — `GET /messages`, дальше опрос `?after_id=` раз в 10 с,
 * только пока экран открыт и вкладка видима (скрыли вкладку — опрос стоит, вернулись — сразу догоняет и продолжает).
 * Новые ответы менеджера при открытом экране отмечаются прочитанными (`POST /messages/read`), бейдж `/me.unread`
 * обновляется ответом ERP. Отправка — оптимистичная строка «отправляется»; не ушла — «Повторить» тем же ключом.
 */
export function useMessagesFeed({ initialUnread }: { initialUnread: number }) {
  const client = useQueryClient();
  const feed = useQuery({ queryKey: keys.messages, queryFn: () => portal.listMessages() });
  const ready = feed.isSuccess;

  const poll = useCallback(async () => {
    for (let page = 0; page < MAX_CATCH_UP_PAGES; page += 1) {
      const current = client.getQueryData<portal.PortalMessagePage>(keys.messages);
      if (!current) return;
      const afterId = lastMessageId(current.items) ?? 0;
      let next: portal.PortalMessagePage;
      try {
        next = await portal.listMessages({ after_id: afterId });
      } catch {
        return; // сеть или сервер — следующий опрос попробует снова, лента остаётся как есть
      }
      client.setQueryData<portal.PortalMessagePage>(keys.messages, (old) => ({
        items: mergeMessages(old?.items ?? [], next.items),
        has_more: old?.has_more ?? false,
      }));
      if (!next.has_more) return;
    }
  }, [client]);

  useVisiblePolling(ready, poll);
  useMarkRead(feed.data?.items, initialUnread);

  const [pending, setPending] = useState<PendingMessage[]>([]);
  const send = useMutation({
    mutationFn: (item: PendingMessage) =>
      portal.postMessage({
        text: item.text,
        client_message_id: item.clientMessageId,
        context: item.context ? { kind: item.context.kind, id: item.context.id } : null,
      }),
    onMutate: (item) => upsertPending(setPending, { ...item, status: 'sending' }),
    onSuccess: (message, item) => {
      client.setQueryData<portal.PortalMessagePage>(keys.messages, (old) => ({
        items: mergeMessages(old?.items ?? [], [message]),
        has_more: old?.has_more ?? false,
      }));
      setPending((list) => list.filter((entry) => entry.clientMessageId !== item.clientMessageId));
    },
    onError: (_error, item) => upsertPending(setPending, { ...item, status: 'failed' }),
  });

  const submit = (text: string, context: portal.MessageContext | null) =>
    send.mutate({ clientMessageId: newClientMessageId(), text, context, status: 'sending' });
  const retry = (item: PendingMessage) => send.mutate({ ...item, status: 'sending' });

  const messages = feed.data?.items ?? [];
  return { feed, messages, pending: unsentPending(pending, messages), submit, retry };
}

function upsertPending(setPending: (update: (list: PendingMessage[]) => PendingMessage[]) => void, item: PendingMessage) {
  setPending((list) =>
    list.some((entry) => entry.clientMessageId === item.clientMessageId)
      ? list.map((entry) => (entry.clientMessageId === item.clientMessageId ? item : entry))
      : [...list, item],
  );
}

/** Опрос по таймеру, только пока вкладка видима; без экрана (размонтирован) — опроса нет. */
function useVisiblePolling(enabled: boolean, poll: () => Promise<void>) {
  useEffect(() => {
    if (!enabled) return;
    let timer: number | undefined;
    const start = () => {
      if (timer === undefined && document.visibilityState === 'visible') {
        timer = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
      }
    };
    const stop = () => {
      if (timer !== undefined) window.clearInterval(timer);
      timer = undefined;
    };
    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        void poll();
        start();
      } else {
        stop();
      }
    };
    start();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [enabled, poll]);
}

/**
 * «Прочитано»: при открытом экране и видимой вкладке — отметка до последнего сообщения ленты, если в ней есть ответ
 * менеджера новее отмеченного (при входе на экран — если `/me.unread` не ноль). Ответ ERP — новое число для бейджа.
 */
function useMarkRead(items: portal.PortalMessage[] | undefined, initialUnread: number) {
  const client = useQueryClient();
  const marked = useRef<number | null>(null);
  useEffect(() => {
    if (!items || document.visibilityState !== 'visible') return;
    const lastId = lastMessageId(items);
    const managerId = lastManagerId(items);
    // Первая загрузка: всё уже прочитано — отмечать нечего, ждём новых ответов менеджера
    if (marked.current === null) marked.current = initialUnread > 0 ? 0 : managerId;
    if (lastId === null || managerId <= marked.current) return;
    marked.current = lastId;
    portal
      .markMessagesRead(lastId)
      .then(({ unread }) =>
        client.setQueryData<portal.Me | null>(ME_QUERY_KEY, (me) => (me ? { ...me, unread } : me)),
      )
      .catch(() => {
        marked.current = 0; // не отметилось — попробуем со следующей лентой
      });
  }, [items, initialUnread, client]);
}
