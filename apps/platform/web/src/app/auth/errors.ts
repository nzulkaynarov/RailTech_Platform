import type { TFunction } from "i18next";

import { ApiError } from "../../shared/api/errors";
import i18n from "../../shared/i18n";

/**
 * Текст ошибки по `Error.code` (контракт BFF): словарь экрана, иначе `default`. Сообщение сервера на экран не выводим —
 * оно «для сотрудника», но формулировки экрана входа ведёт SPA (три языка, одинаковый тон).
 */
export function authErrorText(
  t: TFunction<"shell">,
  group: "login" | "changePassword" | "setup",
  error: unknown,
): string {
  const code = error instanceof ApiError ? error.code : "";
  const key = `${group}.errors.${code}`;
  return i18n.exists(key, { ns: "shell" }) ? t(key) : t(`${group}.errors.default`);
}
