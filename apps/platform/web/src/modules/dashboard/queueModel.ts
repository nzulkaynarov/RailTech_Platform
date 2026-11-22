import type {
  QueueCategory,
  QueueGroup,
  QueueItem,
  WaitingRow,
} from "../../shared/api/generated/model";

/** Группы «Что ждёт вас» в порядке показа (ГЛ-1): просрочено, сегодня, позже. */
export const GROUP_ORDER: readonly QueueGroup[] = ["overdue", "today", "later"];

/** Виды работы в порядке чипов фильтра: сначала решения, потом исполнение. */
export const CATEGORY_ORDER: readonly QueueCategory[] = [
  "sign",
  "approve",
  "resolution",
  "instruction",
  "payment",
  "lead",
  "mail",
  "supply",
  "project",
  "other",
];

/** Группа строки: ответ BFF, а у старого ответа — из срока (тот же вывод, что на стороне BFF). */
export function groupOf(item: Pick<QueueItem, "group" | "due_label">): QueueGroup {
  if (item.group) return item.group;
  return item.due_label === "overdue" ? "overdue" : item.due_label === "today" ? "today" : "later";
}

export function categoryOf(item: Pick<QueueItem, "category">): QueueCategory {
  return item.category ?? "other";
}

export interface Chip {
  category: QueueCategory;
  count: number;
}

/** Чипы фильтра: только виды, по которым есть строки; счётчик — число строк этого вида (до фильтра по «за {имя}» тоже). */
export function chipsOf(items: readonly Pick<QueueItem, "category">[]): Chip[] {
  const counts = new Map<QueueCategory, number>();
  for (const item of items) {
    const category = categoryOf(item);
    counts.set(category, (counts.get(category) ?? 0) + 1);
  }
  return CATEGORY_ORDER.flatMap((category) => {
    const count = counts.get(category);
    return count ? [{ category, count }] : [];
  });
}

export interface GroupBlock {
  group: QueueGroup;
  items: QueueItem[];
}

/** Строки по группам; пустые группы не показываются. Порядок внутри группы — как прислал BFF (срок, потом давность). */
export function groupsOf(items: readonly QueueItem[]): GroupBlock[] {
  return GROUP_ORDER.flatMap((group) => {
    const own = items.filter((item) => groupOf(item) === group);
    return own.length > 0 ? [{ group, items: own }] : [];
  });
}

/** Быстрое действие в самой строке — только простое (ГЛ-1 п. 3); остальное открывает объект. */
export type QuickAction = "acknowledge" | "take";

export function quickActionOf(
  item: Pick<QueueItem, "kind" | "on_behalf_of" | "id">,
): QuickAction | null {
  // Строка «за {имя}»: ознакомление и «Взять» от чужого имени не делаем — открываем объект
  if (item.on_behalf_of) return null;
  if (item.kind === "acquaint") return "acknowledge";
  if (item.kind === "take_lead") return "take";
  return null;
}

/** Идентификатор письма в строке «Ознакомиться»: `acquaint:<id письма>`. */
export function acquaintLetterId(id: string): string {
  return id.startsWith("acquaint:") ? id.slice("acquaint:".length) : id;
}

/** Возраст «ждёт»: «40 мин», «2 ч», «3 д» — ключ единицы и число. */
export function ageOf(
  since: string,
  now: number,
): { unit: "minutes" | "hours" | "days"; count: number } {
  const seconds = Math.max(0, Math.floor((now - Date.parse(since)) / 1000));
  if (seconds < 3600) return { unit: "minutes", count: Math.max(1, Math.floor(seconds / 60)) };
  if (seconds < 86400) return { unit: "hours", count: Math.floor(seconds / 3600) };
  return { unit: "days", count: Math.floor(seconds / 86400) };
}

/** Напомнить можно: BFF сказал «можно» и срок после прошлого напоминания вышел. */
export function canRemind(
  row: Pick<WaitingRow, "remindable" | "remind_available_at">,
  now: number,
): boolean {
  if (!row.remindable) return false;
  return !row.remind_available_at || Date.parse(row.remind_available_at) <= now;
}
