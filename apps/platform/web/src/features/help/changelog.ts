/**
 * «Что нового» (W-REL): записи `docs/kb/help/changelog/<дата>.md` (копия в `src/generated/help-articles/changelog` —
 * `pnpm kb:sync`, равенство проверяет `changelog.test.ts`). Запись — одна выкладка: черновик собирает
 * `scripts/release_notes.py` из строк «Для пользователей» влитых PR, правит и вливает архитектор (PR).
 *
 * Формат: front matter (`date: ГГГГ-ММ-ДД`, `title`), затем пункты `- **Роли:** текст` («Все», «Директор», «Снабженец,
 * главный инженер»). Пункт без пометки — для всех.
 */
const files = import.meta.glob<string>("../../generated/help-articles/changelog/*.md", {
  query: "?raw",
  import: "default",
  eager: true,
});

export interface ChangelogItem {
  /** Для кого: «Директор», «Менеджер»; пусто — для всех */
  roles: readonly string[];
  text: string;
}

export interface ChangelogEntry {
  /** Дата выкладки `ГГГГ-ММ-ДД` — она же отметка «прочитано» в профиле (`Me.whats_new_read`) */
  date: string;
  title: string;
  items: readonly ChangelogItem[];
}

const ALL = new Set(["все", "всем", "для всех"]);
const ITEM = /^[-*]\s+(?:\*\*(.+?):\*\*\s*)?(.+)$/;

export function parseEntry(name: string, source: string): ChangelogEntry {
  const match = /^---\n([\s\S]*?)\n---\n?([\s\S]*)$/.exec(source);
  const meta = new Map<string, string>();
  for (const line of (match?.[1] ?? "").split("\n")) {
    const at = line.indexOf(":");
    if (at > 0) meta.set(line.slice(0, at).trim(), line.slice(at + 1).trim());
  }
  const items: ChangelogItem[] = [];
  for (const line of (match?.[2] ?? source).split("\n")) {
    const item = ITEM.exec(line.trim());
    if (!item?.[2]) continue;
    const roles = (item[1] ?? "")
      .split(",")
      .map((role) => role.trim())
      .filter((role) => role !== "" && !ALL.has(role.toLocaleLowerCase("ru")));
    items.push({ roles, text: item[2].trim() });
  }
  const date = meta.get("date") ?? name;
  return { date, title: meta.get("title") ?? date, items };
}

function load(): ChangelogEntry[] {
  return Object.entries(files)
    .map(([path, source]) =>
      parseEntry(path.split("/").pop()?.replace(/\.md$/, "") ?? path, source),
    )
    .sort((a, b) => b.date.localeCompare(a.date));
}

/** Записи — новые сверху. */
export const CHANGELOG: readonly ChangelogEntry[] = load();

/** Дата последней записи; нет записей — `undefined` (окна «Платформа обновлена» нет). */
export const LATEST_WHATS_NEW: string | undefined = CHANGELOG[0]?.date;

/** Есть запись новее отметки (`null` — ничего не видел). Поле не пришло (`undefined`) — не знаем, не показываем. */
export function isNewer(mark: string | null | undefined, latest: string | undefined): boolean {
  if (latest === undefined || mark === undefined) return false;
  return mark === null || mark < latest;
}

/** «2026-10-28» → «28 октября 2026» на языке интерфейса. */
export function entryDate(date: string, language: string): string {
  const parsed = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return date;
  return new Intl.DateTimeFormat(language === "uz" ? "uz-Latn" : language, {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(parsed);
}
