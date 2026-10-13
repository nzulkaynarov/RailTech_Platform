/** Шаблоны ответов, профиль бота и экспорт CSV (аудит 2026-10-12 §3, §5). */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  createReplyTemplate,
  deleteReplyTemplate,
  getExportClientsUrl,
  getExportDealsUrl,
  getExportLeadsUrl,
  getGetTelegramProfileQueryKey,
  getListReplyTemplatesQueryKey,
  putTelegramProfile,
  updateReplyTemplate,
  useGetTelegramProfile,
  useListReplyTemplates,
} from "./generated/crm";
import type {
  BotProfileSettings,
  ExportClientsParams,
  ExportDealsParams,
  ExportLeadsParams,
  ReplyTemplateIn,
} from "./generated/model";
import { compact, downloadFile } from "./http";

export const useReplyTemplates = (enabled = true) =>
  useListReplyTemplates({ query: { enabled, staleTime: 60_000 } });

export function useReplyTemplateMutations(onError: (error: unknown) => void) {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: getListReplyTemplatesQueryKey() });
  return {
    save: useMutation({
      mutationFn: async ({ id, body }: { id: number | null; body: ReplyTemplateIn }) =>
        id === null ? await createReplyTemplate(body) : await updateReplyTemplate(id, body),
      onSuccess: () => void refresh(),
      onError,
    }),
    remove: useMutation({
      mutationFn: (id: number) => deleteReplyTemplate(id),
      onSuccess: () => void refresh(),
      onError,
    }),
  };
}

export const useBotProfile = () => useGetTelegramProfile();

export function useSaveBotProfile(onError: (error: unknown) => void) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: BotProfileSettings) => putTelegramProfile(body),
    onSuccess: (next) => {
      client.setQueryData(getGetTelegramProfileQueryKey(), next);
    },
    onError,
  });
}

type Exportable =
  | { entity: "leads"; params: ExportLeadsParams }
  | { entity: "clients"; params: ExportClientsParams }
  | { entity: "deals"; params: ExportDealsParams };

/** Скачать CSV с текущими фильтрами списка (только админ, `export:read`). */
export async function downloadCsv(target: Exportable): Promise<void> {
  const url =
    target.entity === "leads"
      ? getExportLeadsUrl(compact(target.params))
      : target.entity === "clients"
        ? getExportClientsUrl(compact(target.params))
        : getExportDealsUrl(compact(target.params));
  const stamp = new Date().toISOString().slice(0, 10);
  await downloadFile(url, `${target.entity}-${stamp}.csv`);
}
