import type { TFunction } from "i18next";

import { ApiError } from "../../shared/api/errors";
import i18n from "../../shared/i18n";

export type ErrorGroup = "photo" | "data" | "telegram" | "deputy" | "forgot" | "reset";

/**
 * Текст ошибки словами из словаря `profile:<группа>.errors`: сначала подкод CRM (`details.reason` — «телефон неверен»),
 * затем код ошибки BFF, иначе общий текст группы. Сообщение сервера на экран не выводим.
 */
export function profileErrorText(
  t: TFunction<"profile">,
  group: ErrorGroup,
  error: unknown,
): string {
  if (error instanceof ApiError) {
    const reason = error.details["reason"];
    for (const key of [typeof reason === "string" ? reason : "", error.code]) {
      const path = `${group}.errors.${key}`;
      if (key && i18n.exists(path, { ns: "profile" })) return t(path);
    }
  }
  return t(`${group}.errors.default`);
}
