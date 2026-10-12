import { App as AntApp } from "antd";
import { useCallback } from "react";

import { ApiError } from "../api/http";
import { errorText, t } from "../i18n/ru";

/** Подкод из `details.reason` → текст; `{name}` — кто уже забрал лида, `{error}` — ответ Telegram. */
function reasonText(error: ApiError): string | null {
  const reason = error.details["reason"];
  if (typeof reason !== "string") return null;
  const text = t.apiReasons[reason];
  if (!text) return null;
  const name = error.details["assigned_user_name"];
  const cause = error.details["telegram_error"];
  return text
    .replace("{name}", typeof name === "string" && name ? name : t.common.colleague)
    .replace("{error}", typeof cause === "string" && cause ? cause : t.common.none);
}

/**
 * Текст ошибки API для пользователя (ADR-0017): подкод `details.reason` → словарь `reasons`,
 * иначе класс ошибки `code` → `errors`, иначе сообщение сервера; сетевой сбой или голый
 * HTTP-статус — общий текст.
 */
export function apiErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError) || error.code === "http_error") return errorText(undefined);
  return reasonText(error) ?? errorText(error.code, error.message || undefined);
}

/** Поле формы, к которому относится ошибка (`details.field`), чтобы подсветить его. */
export function apiErrorField(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const field = error.details["field"];
  return typeof field === "string" && field ? field : null;
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
