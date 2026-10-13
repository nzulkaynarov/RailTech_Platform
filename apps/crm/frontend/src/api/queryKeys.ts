/**
 * Группы ключей кэша для инвалидации (ADR-0021).
 *
 * Ключи генерирует orval: `[url]` или `[url, params]`. Префиксное совпадение TanStack Query
 * работает только внутри одного URL (`["/api/v1/leads"]` накрывает все страницы списка),
 * но не между ресурсами: карточка лида, переписка и заметки — разные URL. Поэтому
 * связанные ключи перечисляются здесь явно, и SSE, мутации и страницы берут их отсюда.
 */
import type { QueryClient, QueryKey } from "@tanstack/react-query";

import {
  getGetLeadQueryKey,
  getInboxQueryKey,
  getLeadDecisionsQueryKey,
  getLeadMessagesQueryKey,
  getLeadNotesQueryKey,
  getListKbDocumentsQueryKey,
  getListKbGapsQueryKey,
  getListLeadsQueryKey,
  getListProductsQueryKey,
  getListServiceRequestsQueryKey,
} from "./generated/crm";

export const queryKeys = {
  /** Карточка лида целиком: шапка, переписка, заметки, решения ИИ. */
  lead: (id: number): QueryKey[] => [
    getGetLeadQueryKey(id),
    getLeadMessagesQueryKey(id),
    getLeadNotesQueryKey(id),
    getLeadDecisionsQueryKey(id),
  ],
  /** Списки, где виден лид: входящие, открытые запросы клиентов, все страницы «Лидов». */
  leadLists: (): QueryKey[] => [
    getInboxQueryKey(),
    getListServiceRequestsQueryKey(),
    getListLeadsQueryKey(),
  ],
  /** База знаний: документы, продукты, пробелы (чанки документа перечитываются при открытии). */
  kb: (): QueryKey[] => [
    getListKbDocumentsQueryKey(),
    getListProductsQueryKey(),
    getListKbGapsQueryKey(),
  ],
};

/** Пометить ключи устаревшими; активные запросы перечитываются сразу. */
export async function invalidateKeys(
  client: QueryClient,
  keys: readonly QueryKey[],
): Promise<void> {
  await Promise.all(keys.map((queryKey) => client.invalidateQueries({ queryKey })));
}
