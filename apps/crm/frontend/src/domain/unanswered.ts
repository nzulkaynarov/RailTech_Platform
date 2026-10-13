import type { MessageOut } from "../api/generated/model";

/**
 * Последнее сообщение клиента, на которое никто не ответил (ни менеджер, ни бот), — текст
 * для предупреждения перед «Вернуть боту»: бот отвечает только на новые сообщения.
 */
export function lastUnanswered(messages: readonly MessageOut[] | undefined): string | null {
  const last = messages?.at(-1);
  if (!last || last.role !== "lead") return null;
  const text = last.text.trim();
  return text ? (text.length > 140 ? `${text.slice(0, 140)}…` : text) : null;
}
