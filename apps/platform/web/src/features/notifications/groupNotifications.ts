import type { Notification } from "../../shared/api/generated/model";

/** Объект уведомления для склейки: вид и номер; уведомление без объекта — само по себе. */
export function objectKey(item: Pick<Notification, "id" | "object">): string {
  return item.object ? `${item.object.kind}:${item.object.number}` : `own:${item.id}`;
}

export interface NotificationGroup {
  key: string;
  /** Самое новое уведомление — его заголовок и время на строке группы */
  head: Notification;
  /** Все уведомления объекта, новые сверху */
  items: Notification[];
  unread: number;
  needsAction: boolean;
}

const time = (item: Notification) => Date.parse(item.created_at);

/**
 * Колокольчик по порядку (УВЕД-1): события одного объекта — одна строка со счётчиком; непрочитанные группы выше
 * прочитанных, внутри — новые выше.
 */
export function groupNotifications(items: readonly Notification[]): NotificationGroup[] {
  const byKey = new Map<string, Notification[]>();
  for (const item of items) {
    const key = objectKey(item);
    const list = byKey.get(key);
    if (list) list.push(item);
    else byKey.set(key, [item]);
  }
  const groups: NotificationGroup[] = [];
  for (const [key, list] of byKey) {
    list.sort((a, b) => time(b) - time(a));
    const [head] = list;
    if (!head) continue;
    groups.push({
      key,
      head,
      items: list,
      unread: list.filter((n) => !n.read).length,
      needsAction: list.some((n) => !n.read && n.needs_action === true),
    });
  }
  groups.sort((a, b) => {
    if (a.unread > 0 !== b.unread > 0) return a.unread > 0 ? -1 : 1;
    return time(b.head) - time(a.head);
  });
  return groups;
}
