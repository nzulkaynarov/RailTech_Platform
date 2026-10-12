/** Шаблоны ответов, профиль бота и экспорт CSV (аудит 2026-10-12 §3, §5). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createReplyTemplate,
  deleteReplyTemplate,
  getExportClientsUrl,
  getExportDealsUrl,
  getExportLeadsUrl,
  getTelegramProfile,
  listReplyTemplates,
  putTelegramProfile,
  updateReplyTemplate,
} from "./generated/crm";
import type {
  BotProfileSettings,
  ExportClientsParams,
  ExportDealsParams,
  ExportLeadsParams,
  ReplyTemplateIn,
} from "./generated/model";
import { compact, downloadFile, unwrap } from "./http";

export const templateKeys = {
  list: ["reply-templates"] as const,
  profile: ["integrations", "telegram", "profile"] as const,
};

export const useReplyTemplates = (enabled = true) =>
  useQuery({
    queryKey: templateKeys.list,
    queryFn: async () => unwrap(await listReplyTemplates()),
    enabled,
    staleTime: 60_000,
  });

export function useReplyTemplateMutations(onError: (error: unknown) => void) {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: templateKeys.list });
  return {
    save: useMutation({
      mutationFn: async ({ id, body }: { id: number | null; body: ReplyTemplateIn }) =>
        id === null
          ? unwrap(await createReplyTemplate(body))
          : unwrap(await updateReplyTemplate(id, body)),
      onSuccess: () => void refresh(),
      onError,
    }),
    remove: useMutation({
      mutationFn: async (id: number) => unwrap(await deleteReplyTemplate(id)),
      onSuccess: () => void refresh(),
      onError,
    }),
  };
}

export const useBotProfile = () =>
  useQuery({
    queryKey: templateKeys.profile,
    queryFn: async () => unwrap(await getTelegramProfile()),
  });

export function useSaveBotProfile(onError: (error: unknown) => void) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: BotProfileSettings) => unwrap(await putTelegramProfile(body)),
    onSuccess: (next) => {
      client.setQueryData(templateKeys.profile, next);
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
