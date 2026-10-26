/**
 * «Что изменилось» в записи аудита: `before` и `after` приходят из CRM произвольными словарями. Здесь они
 * разворачиваются в плоские пути и сравниваются; слова к полям и значениям даёт экран.
 */
export type Json = Record<string, unknown>;

export interface FieldChange {
  /** Путь поля: `name`, `access.crm.leads` */
  path: string;
  before?: unknown;
  after?: unknown;
}

/** Служебные поля, которые человеку ничего не говорят (id ролей — есть названия `platform_role_names`). */
const HIDDEN = new Set(["platform_role_ids"]);

function flatten(record: Json, prefix = ""): Map<string, unknown> {
  const out = new Map<string, unknown>();
  for (const [key, value] of Object.entries(record)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      for (const [p, v] of flatten(value as Json, path)) out.set(p, v);
    } else {
      out.set(path, value);
    }
  }
  return out;
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** Только отличающиеся поля; при создании — только «после», при удалении — только «до». */
export function auditChanges(before?: Json | null, after?: Json | null): FieldChange[] {
  const was = flatten(before ?? {});
  const now = flatten(after ?? {});
  const paths = [...new Set([...was.keys(), ...now.keys()])];
  return paths
    .filter((path) => !HIDDEN.has(path.split(".")[0] ?? path))
    .filter((path) => !same(was.get(path), now.get(path)))
    .map((path) => ({
      path,
      ...(was.has(path) ? { before: was.get(path) } : {}),
      ...(now.has(path) ? { after: now.get(path) } : {}),
    }));
}

/** Значение поля текстом; пустое — `null` (экран подставит «не указано»), булевы — `yes`/`no` решает экран. */
export function scalarText(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (Array.isArray(value)) {
    const items = value.map(scalarText).filter((v): v is string => v !== null);
    return items.length ? items.join(", ") : null;
  }
  const text =
    typeof value === "string"
      ? value
      : typeof value === "number" || typeof value === "boolean" || typeof value === "bigint"
        ? String(value)
        : JSON.stringify(value);
  return text.length > 160 ? `${text.slice(0, 159)}…` : text;
}
