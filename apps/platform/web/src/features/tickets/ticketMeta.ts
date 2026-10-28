import type { TFunction } from "i18next";

import { ApiError } from "../../shared/api/errors";
import { TicketStatus, TicketSubject } from "../../shared/api/generated/model";
import i18n from "../../shared/i18n";

export const TICKET_SUBJECTS: readonly TicketSubject[] = [
  TicketSubject.access,
  TicketSubject.notification,
  TicketSubject.template,
  TicketSubject.error,
  TicketSubject.other,
];
export const TICKET_STATUSES: readonly TicketStatus[] = [
  TicketStatus.new,
  TicketStatus.in_progress,
  TicketStatus.resolved,
];

/** Максимум символов текста обращения: тот же, что у CRM (`ticket_text_too_long`). */
export const TICKET_TEXT_MAX = 4000;

/** Текст ошибки словами: сначала подкод CRM, затем код BFF, иначе общий. Сообщение сервера на экран не выводим. */
export function ticketErrorText(
  t: TFunction<"help">,
  group: "write" | "admin.card",
  error: unknown,
) {
  const base = group === "write" ? "write.errors" : "admin.card.errors";
  if (error instanceof ApiError) {
    const reason = error.details["reason"];
    for (const key of [typeof reason === "string" ? reason : "", error.code]) {
      if (key && i18n.exists(`${base}.${key}`, { ns: "help" })) return t(`${base}.${key}`);
    }
  }
  return t(`${base}.default`);
}
