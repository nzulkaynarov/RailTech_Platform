/** Запросы «Подключений»: статус бота, найденные каналы, мутации (токен, канал, тест). */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  connectTelegramChannel,
  getGetTelegramProfileQueryKey,
  getGetTelegramStatusQueryKey,
  getListTelegramChannelsQueryKey,
  putTelegramToken,
  useGetTelegramStatus,
  useListTelegramChannels,
  useSendTelegramChannelTest,
} from "./generated/crm";
import type { TelegramTokenIn } from "./generated/model";

export const useTelegramStatus = () => useGetTelegramStatus();

export const useTelegramChannels = () => useListTelegramChannels();

export function useTelegramMutations(onError: (error: unknown) => void) {
  const client = useQueryClient();
  const statusKey = getGetTelegramStatusQueryKey();
  return {
    saveToken: useMutation({
      mutationFn: (body: TelegramTokenIn) => putTelegramToken(body),
      onSuccess: (status) => {
        client.setQueryData(statusKey, status);
      },
      onError,
    }),
    connect: useMutation({
      mutationFn: (chatId: number) => connectTelegramChannel(chatId),
      // Канал подключён: перечитать статус, найденные каналы и профиль бота.
      onSuccess: () => {
        for (const queryKey of [
          statusKey,
          getListTelegramChannelsQueryKey(),
          getGetTelegramProfileQueryKey(),
        ])
          void client.invalidateQueries({ queryKey });
      },
      onError,
    }),
    sendTest: useSendTelegramChannelTest({ mutation: { onError } }),
  };
}
