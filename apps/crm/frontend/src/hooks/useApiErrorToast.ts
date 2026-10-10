import { App as AntApp } from "antd";
import { useCallback } from "react";

import { ApiError } from "../api/http";
import { errorText } from "../i18n/ru";

/**
 * Текст ошибки API для пользователя: известный код → словарь, иначе сообщение сервера;
 * сетевой сбой или голый HTTP-статус — общий текст.
 */
export function apiErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError) || error.code === "http_error") return errorText(undefined);
  return errorText(error.code, error.message || undefined);
}

/**
 * Единый обработчик ошибки мутации: тост с понятным текстом (`errors.*`). Тосты
 * попадают в live-регион (app/liveRegion.ts), поэтому озвучиваются скринридером.
 * Использование: `useMutation({ ..., onError: useApiErrorToast() })`.
 */
export function useApiErrorToast(): (error: unknown) => void {
  const { message } = AntApp.useApp();
  return useCallback(
    (error: unknown) => {
      void message.error(apiErrorMessage(error));
    },
    [message],
  );
}
