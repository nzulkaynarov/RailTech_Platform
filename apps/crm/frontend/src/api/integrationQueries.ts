/** Запросы «Подключений»: статус бота, найденные каналы, коннектор ERP, мутации. */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  checkErpConnection,
  connectTelegramChannel,
  getGetErpStatusQueryKey,
  getGetTelegramProfileQueryKey,
  getGetTelegramStatusQueryKey,
  getListTelegramChannelsQueryKey,
  getSystemStatusQueryKey,
  putErpConnector,
  putTelegramToken,
  useGetErpStatus,
  useGetTelegramStatus,
  useListTelegramChannels,
  useSendTelegramChannelTest,
} from "./generated/crm";
import type { ErpConnectorIn, TelegramTokenIn } from "./generated/model";

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

export const useErpStatus = () => useGetErpStatus();

/** Коннектор ERP (M3-CRM-02): сохранение меняет режим и здоровье — «Состояние» перечитывается. */
export function useErpMutations(onError: (error: unknown) => void) {
  const client = useQueryClient();
  const statusKey = getGetErpStatusQueryKey();
  const systemKey = getSystemStatusQueryKey();
  return {
    save: useMutation({
      mutationFn: (body: ErpConnectorIn) => putErpConnector(body),
      onSuccess: (status) => {
        client.setQueryData(statusKey, status);
        void client.invalidateQueries({ queryKey: systemKey });
      },
      onError,
    }),
    check: useMutation({
      mutationFn: () => checkErpConnection(),
      // Итог проверки показывается в карточке (и успех, и ошибка) — тост не нужен.
      onSettled: () => void client.invalidateQueries({ queryKey: systemKey }),
    }),
  };
}
