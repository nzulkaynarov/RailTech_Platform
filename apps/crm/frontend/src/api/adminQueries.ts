/** Запросы админки (Фаза 5): база знаний, пробелы, настройки, дашборд, аудит. */
import { useQuery } from "@tanstack/react-query";

import {
  documentAccess,
  getClient,
  getDashboard,
  listClientContacts,
  listClients,
  listDocuments,
  getSettings,
  listAudit,
  listKbChunks,
  listKbDocuments,
  listKbGaps,
  listProducts,
  systemStatus,
} from "./generated/crm";
import type { ListAuditParams, ListKbGapsParams } from "./generated/model";
import { compact, unwrap } from "./http";

export const adminKeys = {
  documents: ["kb", "documents"] as const,
  chunks: (id: number) => ["kb", "documents", id, "chunks"] as const,
  products: ["kb", "products"] as const,
  gaps: (params: ListKbGapsParams) => ["kb", "gaps", params] as const,
  settings: ["settings"] as const,
  dashboard: (days: number) => ["dashboard", days] as const,
  audit: (params: ListAuditParams) => ["audit", params] as const,
  clients: (q: string) => ["clients", q] as const,
  client: (id: number) => ["client", id] as const,
  clientDocuments: (id: number) => ["client", id, "documents"] as const,
  clientContacts: (id: number) => ["client", id, "contacts"] as const,
  access: (id: number) => ["document", id, "access"] as const,
  system: ["system", "status"] as const,
};

/** «Состояние системы»: только чтение, моделей не вызывает; авто-обновление раз в минуту. */
export const useSystemStatus = () =>
  useQuery({
    queryKey: adminKeys.system,
    queryFn: async () => unwrap(await systemStatus()),
    refetchInterval: 60_000,
  });

export const useKbDocuments = () =>
  useQuery({
    queryKey: adminKeys.documents,
    queryFn: async () => unwrap(await listKbDocuments()),
    // Пока документы индексируются — обновляем статус раз в 3 с.
    refetchInterval: (query) =>
      query.state.data?.some((d) => ["pending", "processing"].includes(d.ingest_status))
        ? 3000
        : false,
  });

export const useKbChunks = (id: number | null) =>
  useQuery({
    queryKey: adminKeys.chunks(id ?? 0),
    queryFn: async () => unwrap(await listKbChunks(id ?? 0)),
    enabled: id !== null,
  });

export const useProducts = () =>
  useQuery({ queryKey: adminKeys.products, queryFn: async () => unwrap(await listProducts()) });

export const useKbGaps = (params: ListKbGapsParams) =>
  useQuery({
    queryKey: adminKeys.gaps(params),
    queryFn: async () => unwrap(await listKbGaps(compact(params))),
  });

export const useSettings = () =>
  useQuery({ queryKey: adminKeys.settings, queryFn: async () => unwrap(await getSettings()) });

export const useDashboard = (days: number) =>
  useQuery({
    queryKey: adminKeys.dashboard(days),
    queryFn: async () => unwrap(await getDashboard({ days })),
  });

export const useAudit = (params: ListAuditParams) =>
  useQuery({
    queryKey: adminKeys.audit(params),
    queryFn: async () => unwrap(await listAudit(compact(params))),
  });

export const useClients = (q: string) =>
  useQuery({
    queryKey: adminKeys.clients(q),
    queryFn: async () => unwrap(await listClients(compact({ q }))),
  });

export const useClient = (id: number) =>
  useQuery({ queryKey: adminKeys.client(id), queryFn: async () => unwrap(await getClient(id)) });

export const useClientContacts = (id: number) =>
  useQuery({
    queryKey: adminKeys.clientContacts(id),
    queryFn: async () => unwrap(await listClientContacts(id)),
  });

export const useClientDocuments = (id: number) =>
  useQuery({
    queryKey: adminKeys.clientDocuments(id),
    queryFn: async () => unwrap(await listDocuments({ client_id: id })),
    refetchInterval: (query) =>
      query.state.data?.some((d) => d.extract_status === "pending") ? 3000 : false,
  });

export const useDocumentAccess = (id: number | null) =>
  useQuery({
    queryKey: adminKeys.access(id ?? 0),
    queryFn: async () => unwrap(await documentAccess(id ?? 0)),
    enabled: id !== null,
  });
