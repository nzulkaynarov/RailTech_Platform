/** Запросы «Подключений»: статус бота, найденные каналы, мутации (токен, канал, тест). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  connectTelegramChannel,
  getTelegramStatus,
  listTelegramChannels,
  putTelegramToken,
  sendTelegramChannelTest,
} from "./generated/crm";
import type { TelegramTokenIn } from "./generated/model";
import { unwrap } from "./http";

export const integrationKeys = {
  telegram: ["integrations", "telegram"] as const,
  channels: ["integrations", "telegram", "channels"] as const,
};

export const useTelegramStatus = () =>
  useQuery({
    queryKey: integrationKeys.telegram,
    queryFn: async () => unwrap(await getTelegramStatus()),
  });

export const useTelegramChannels = () =>
  useQuery({
    queryKey: integrationKeys.channels,
    queryFn: async () => unwrap(await listTelegramChannels()),
  });

export function useTelegramMutations(onError: (error: unknown) => void) {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: integrationKeys.telegram });
  return {
    saveToken: useMutation({
      mutationFn: async (body: TelegramTokenIn) => unwrap(await putTelegramToken(body)),
      onSuccess: (status) => {
        client.setQueryData(integrationKeys.telegram, status);
      },
      onError,
    }),
    connect: useMutation({
      mutationFn: async (chatId: number) => unwrap(await connectTelegramChannel(chatId)),
      onSuccess: () => void refresh(),
      onError,
    }),
    sendTest: useMutation({
      mutationFn: async () => unwrap(await sendTelegramChannelTest()),
      onError,
    }),
  };
}
