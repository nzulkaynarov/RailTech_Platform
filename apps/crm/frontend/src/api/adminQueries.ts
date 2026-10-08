/** Запросы админки (Фаза 5): база знаний, пробелы, настройки, дашборд, аудит. */
import { useQuery } from "@tanstack/react-query";

import {
  getDashboard,
  getSettings,
  listAudit,
  listKbChunks,
  listKbDocuments,
  listKbGaps,
  listProducts,
} from "./generated/crm";
import type { ListAuditParams, ListKbGapsParams } from "./generated/model";
import { unwrap } from "./http";

export const adminKeys = {
  documents: ["kb", "documents"] as const,
  chunks: (id: number) => ["kb", "documents", id, "chunks"] as const,
  products: ["kb", "products"] as const,
  gaps: (params: ListKbGapsParams) => ["kb", "gaps", params] as const,
  settings: ["settings"] as const,
  dashboard: (days: number) => ["dashboard", days] as const,
  audit: (params: ListAuditParams) => ["audit", params] as const,
};

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
    queryFn: async () => unwrap(await listKbGaps(params)),
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
    queryFn: async () => unwrap(await listAudit(params)),
  });
