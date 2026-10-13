/** Запросы «Подключений»: статус бота, найденные каналы, коннекторы ERP и «Почта», мутации. */
import { keepPreviousData, useMutation, useQueryClient } from "@tanstack/react-query";

import {
  checkErpConnection,
  checkSmtpConnection,
  connectTelegramChannel,
  getGetErpStatusQueryKey,
  getGetSmtpStatusQueryKey,
  getGetTelegramProfileQueryKey,
  getGetTelegramStatusQueryKey,
  getListEmailLogQueryKey,
  getListTelegramChannelsQueryKey,
  getSystemStatusQueryKey,
  putErpConnector,
  putSmtpConnector,
  putTelegramToken,
  sendSmtpTest,
  useGetErpStatus,
  useGetSmtpStatus,
  useGetTelegramStatus,
  useListEmailLog,
  useListTelegramChannels,
  useSendTelegramChannelTest,
} from "./generated/crm";
import type {
  ErpConnectorIn,
  ListEmailLogParams,
  SmtpConnectorIn,
  TelegramTokenIn,
} from "./generated/model";
import { compact } from "./http";

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

export const useSmtpStatus = () => useGetSmtpStatus();

/** Журнал писем (M3-CRM-08): фильтр по статусу; прошлая страница держится до ответа. */
export const useEmailLog = (params: ListEmailLogParams) =>
  useListEmailLog(compact(params), { query: { placeholderData: keepPreviousData } });

/** Коннектор «Почта» (M3-CRM-08): сохранение, «Проверить связь», тестовое письмо в журнал. */
export function useSmtpMutations(onError: (error: unknown) => void) {
  const client = useQueryClient();
  const statusKey = getGetSmtpStatusQueryKey();
  return {
    save: useMutation({
      mutationFn: (body: SmtpConnectorIn) => putSmtpConnector(body),
      onSuccess: (status) => {
        client.setQueryData(statusKey, status);
      },
      onError,
    }),
    check: useMutation({ mutationFn: () => checkSmtpConnection() }),
    testSend: useMutation({
      mutationFn: () => sendSmtpTest(),
      // Письмо попало в журнал (и без SMTP — строкой «пропущено»): перечитать журнал.
      onSettled: () => void client.invalidateQueries({ queryKey: emailLogKey() }),
      onError,
    }),
  };
}

/** Ключ журнала без параметров — инвалидирует все его фильтры (например, после приглашения). */
export const emailLogKey = () => getListEmailLogQueryKey().slice(0, 1);
