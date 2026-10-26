/** Равенство значений формы (строки, числа, булевы, `null`, массивы и плоские объекты). */
function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

/** Поля, которые человек изменил относительно загруженных значений; только они уходят в PATCH. */
export function changedFields<T extends object>(
  initial: T,
  values: Partial<T> | undefined,
): Partial<T> {
  const out: Partial<T> = {};
  if (!values) return out;
  for (const key of Object.keys(initial) as (keyof T)[]) {
    if (key in values && !same(initial[key], values[key])) out[key] = values[key];
  }
  return out;
}

/** Подпись строки справочника в списке выбора: «USD — Доллар США»; если название уже начинается с кода, код не дублируется. */
export function codeLabel(code: string, name: string): string {
  return name.toLowerCase().startsWith(code.toLowerCase()) ? name : `${code} — ${name}`;
}

/** Копия объекта без перечисленных ключей. */
export function omit<T extends object, K extends keyof T>(
  value: T,
  keys: readonly K[],
): Omit<T, K> {
  const drop = new Set<PropertyKey>(keys);
  return Object.fromEntries(Object.entries(value).filter(([key]) => !drop.has(key))) as Omit<T, K>;
}

export const isEmptyObject = (value: object) => Object.keys(value).length === 0;

/** Пустая строка поля -> `null` для необязательных чисел и ссылок. */
export function blankToNull(value: string | null | undefined): string | null {
  const trimmed = (value ?? "").trim();
  return trimmed === "" ? null : trimmed;
}
