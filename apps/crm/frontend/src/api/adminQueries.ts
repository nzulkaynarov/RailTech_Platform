/** Запросы админки (Фаза 5): база знаний, пробелы, настройки, дашборд, аудит, клиенты. */
import { keepPreviousData } from "@tanstack/react-query";

import {
  getGetClientQueryKey,
  getGetSettingsQueryKey,
  getListClientContactsQueryKey,
  getListDocumentsQueryKey,
  useDocumentAccess as useDocumentAccessQuery,
  useGetClient,
  useGetClientReceivables,
  useGetDashboard,
  useGetSettings,
  useListAudit,
  useListClientContacts,
  useListClients,
  useListDocuments,
  useListKbChunks,
  useListKbDocuments,
  useListKbGaps,
  useListProducts,
  useSystemStatus as useSystemStatusQuery,
} from "./generated/crm";
import type { ListAuditParams, ListKbGapsParams } from "./generated/model";
import { compact } from "./http";

/** Сгенерированные ключи, которые страницы инвалидируют после своих мутаций. */
export const adminKeys = {
  settings: getGetSettingsQueryKey(),
  client: (id: number) => getGetClientQueryKey(id),
  clientDocuments: (id: number) => getListDocumentsQueryKey({ client_id: id }),
  clientContacts: (id: number) => getListClientContactsQueryKey(id),
};

/** «Состояние системы»: только чтение, моделей не вызывает; авто-обновление раз в минуту.
 * Один запрос на странице «Состояние» и в индикаторе шапки (общий ключ кэша). */
export const useSystemStatus = (enabled = true) =>
  useSystemStatusQuery({ query: { refetchInterval: 60_000, enabled } });

export const useKbDocuments = () =>
  useListKbDocuments(undefined, {
    query: {
      // Пока документы индексируются — обновляем статус раз в 3 с.
      refetchInterval: (query) =>
        query.state.data?.some((d) => ["pending", "processing"].includes(d.ingest_status))
          ? 3000
          : false,
    },
  });

export const useKbChunks = (id: number | null) =>
  useListKbChunks(id ?? 0, { query: { enabled: id !== null } });

export const useProducts = () => useListProducts();

/** Списки с фильтрами держат прошлую страницу до ответа — таблица не пустеет. */
export const useKbGaps = (params: ListKbGapsParams) =>
  useListKbGaps(compact(params), { query: { placeholderData: keepPreviousData } });

export const useSettings = () => useGetSettings();

export const useDashboard = (days: number) => useGetDashboard({ days });

export const useAudit = (params: ListAuditParams) =>
  useListAudit(compact(params), { query: { placeholderData: keepPreviousData } });

export const useClients = (q: string) =>
  useListClients(compact({ q }), { query: { placeholderData: keepPreviousData } });

/** Пока клиент «передаётся в бэк-офис» (FIX-31) — перечитываем, чтобы менеджер увидел итог. */
export const useClient = (id: number) =>
  useGetClient(id, {
    query: {
      refetchInterval: (query) =>
        query.state.data?.erp_handoff_status === "pending" ? 4000 : false,
    },
  });

/**
 * Долг клиента по валютам из ERP (шов 0.3.0). Запрос только у клиента, переданного в бэк-офис;
 * сбой не повторяем и не показываем — блок «Долг» просто не появляется (карточка как была).
 */
export const useClientReceivables = (id: number, linkedToErp: boolean) =>
  useGetClientReceivables(id, {
    query: { enabled: linkedToErp, retry: false, staleTime: 60_000 },
  });

export const useClientContacts = (id: number) => useListClientContacts(id);

export const useClientDocuments = (id: number) =>
  useListDocuments(
    { client_id: id },
    {
      query: {
        refetchInterval: (query) =>
          query.state.data?.some((d) => d.extract_status === "pending") ? 3000 : false,
      },
    },
  );

export const useDocumentAccess = (id: number | null) =>
  useDocumentAccessQuery(id ?? 0, { query: { enabled: id !== null } });
