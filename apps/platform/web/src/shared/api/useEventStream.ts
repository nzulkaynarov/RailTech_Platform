import { useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query";
import { useEffect } from "react";

import { EventStreamClient } from "./eventStream";
import type { InvalidationTopic } from "./generated/model";
import {
  getGetActivityTodayQueryKey,
  getGetMenuCountersQueryKey,
  getGetQueueCardsQueryKey,
  getGetQueueQueryKey,
  getListCrmMessagesQueryKey,
  getListNotificationsQueryKey,
} from "./generated/platform-bff";
import { setStreamLive } from "./streamState";

/** Какие запросы перезапрашивает тема подсказки (ключи — префиксы: параметры запроса не важны). */
const QUERY_KEYS: Record<InvalidationTopic, readonly QueryKey[]> = {
  notifications: [getListNotificationsQueryKey()],
  counters: [getGetMenuCountersQueryKey()],
  queue: [getGetQueueQueryKey(), getGetQueueCardsQueryKey()],
  activity: [getGetActivityTodayQueryKey()],
  messages: [getListCrmMessagesQueryKey()],
};

/**
 * Тема `messages` (D1-1): кроме очереди «Ждут ответа» — открытая переписка лида (`/crm/messages/{lead}`, лента `/thread`).
 * Ключи с номером лида префиксом очереди не являются, поэтому — по началу адреса.
 */
const MESSAGES_PREFIX = "/api/v1/crm/messages/";

const ALL_TOPICS = Object.keys(QUERY_KEYS) as InvalidationTopic[];

export function invalidateTopics(client: QueryClient, topics: readonly InvalidationTopic[]): void {
  for (const topic of topics) {
    for (const queryKey of QUERY_KEYS[topic]) void client.invalidateQueries({ queryKey });
  }
  if (topics.includes("messages")) {
    void client.invalidateQueries({
      predicate: (query) => String(query.queryKey[0]).startsWith(MESSAGES_PREFIX),
    });
  }
}

/**
 * Поток подсказок BFF вместо опроса (B5): на событие шины перезапрашивает уведомления, счётчики меню, «Мою очередь» и
 * ленту «Сегодня» обычными API (с проверкой прав — данных событий в потоке нет). Пока поток жив, опрос редкий; при
 * обрыве работает прежний (`usePollQuery`), поток переподключается сам, а после переподключения идёт один полный
 * перезапрос. Подключать один раз, в каркасе вошедшего сотрудника.
 */
export function useEventStream(enabled: boolean): void {
  const client = useQueryClient();
  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;
    const stream = new EventStreamClient({
      onHint: (topics) => {
        invalidateTopics(client, topics);
      },
      onResync: () => {
        invalidateTopics(client, ALL_TOPICS);
      },
      onLive: setStreamLive,
    });
    stream.start();
    return () => {
      stream.stop();
    };
  }, [client, enabled]);
}
