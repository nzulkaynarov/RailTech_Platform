import type {
  ConversationCard,
  ConversationThread,
  Language,
  MessageInboxItem,
  TeamNote,
  ThreadMessage,
} from "../../../shared/api/generated/model";

/** Страница ленты: последние сообщения; «Показать раньше» догружает по столько же. */
export const PAGE_SIZE = 30;

export type Entry =
  | { kind: "message"; at: string; message: ThreadMessage }
  | { kind: "note"; at: string; note: TeamNote };

/**
 * Лента для показа: старые страницы + последняя (по id без повторов), заметки команды — между сообщениями по времени,
 * но не старше самого раннего загруженного сообщения (пока история не догружена целиком).
 */
export function mergeThread(
  older: ThreadMessage[],
  latest: ConversationThread | undefined,
  complete: boolean,
): Entry[] {
  const byId = new Map<number, ThreadMessage>();
  for (const m of [...older, ...(latest?.items ?? [])]) byId.set(m.id, m);
  const messages = [...byId.values()].sort((a, b) => a.id - b.id);
  const oldest = messages[0]?.created_at;
  const notes = (latest?.notes ?? []).filter(
    (n) => complete || !oldest || Date.parse(n.created_at) >= Date.parse(oldest),
  );
  const entries: Entry[] = [
    ...messages.map((message) => ({ kind: "message" as const, at: message.created_at, message })),
    ...notes.map((note) => ({ kind: "note" as const, at: note.created_at, note })),
  ];
  return entries.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
}

/** Передача первой линии (D17G-1): причина `handed_over`, лид у ответственного — забирает только он. */
export function handedOver(item: Pick<MessageInboxItem, "handoff" | "assigned">): boolean {
  return Boolean(item.handoff?.reasons.includes("handed_over") && item.assigned);
}

/**
 * Передачу можно забрать: она открыта (или отложена) и лид ещё ни у кого — или первая линия передала его именно мне
 * (`me`, D17G-1).
 */
export function canTake(
  item: Pick<MessageInboxItem, "handoff" | "assigned" | "group">,
  me?: string,
): boolean {
  if (item.handoff) {
    if (item.handoff.state === "taken") return false;
    // Ответственный уже есть (передача первой линии, кабинет клиента с владельцем): забирает он сам.
    return !item.assigned || item.assigned.id === me;
  }
  return item.group === "unassigned";
}

/** «Забрать» в диалоге, открытом без очереди (из реестра или карточки): лид ещё не у сотрудника (бот, ждёт менеджера). */
export function canTakeCard(
  card: Pick<ConversationCard, "owner_mode" | "assigned">,
  me?: string,
): boolean {
  return card.owner_mode !== "manager" && (!card.assigned || card.assigned.id === me);
}

/** «Передать менеджеру» (первая линия): лида ещё не ведёт сотрудник — бот, ждёт менеджера или передан, но не забран. */
export function canHandOver(card: { owner_mode: "bot" | "waiting" | "manager" }): boolean {
  return card.owner_mode !== "manager";
}

/** Шаблон на языке лида (пусто — русский) с подстановкой `{name}` и `{manager}`. */
export function fillTemplate(
  text: Record<Language, string>,
  language: Language,
  name: string,
  manager: string,
): string {
  const body = text[language] || text.ru;
  return body.replaceAll("{name}", name).replaceAll("{manager}", manager);
}
