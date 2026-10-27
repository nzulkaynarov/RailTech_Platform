import type {
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

/** Передачу можно забрать: она открыта (или отложена), лид ещё ни у кого. */
export function canTake(item: Pick<MessageInboxItem, "handoff" | "assigned" | "group">): boolean {
  if (item.handoff) return item.handoff.state !== "taken" && !item.assigned;
  return item.group === "unassigned";
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
