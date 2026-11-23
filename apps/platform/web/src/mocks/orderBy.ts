/** Значение поля для порядка в моках: строка, число или пусто (`null`, `""`). */
export type OrderValue = string | number | null | undefined;

/**
 * Порядок «щелчком по шапке» (Х-15б) в моках, как на сервере: `field` — по возрастанию, `-field` — по убыванию; поле
 * вне списка не сортирует, пустые значения — в конце при любом направлении, равные остаются в прежнем порядке.
 */
export function orderBy<Row>(
  rows: readonly Row[],
  sort: string | null,
  fields: Record<string, (row: Row) => OrderValue>,
): Row[] {
  const desc = sort?.startsWith("-") ?? false;
  const value = fields[desc ? (sort ?? "").slice(1) : (sort ?? "")];
  if (!value) return [...rows];
  const empty = (row: Row) => value(row) === null || value(row) === undefined || value(row) === "";
  const filled = rows.filter((row) => !empty(row));
  filled.sort((a, b) => {
    const x = value(a);
    const y = value(b);
    const result =
      typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
    return desc ? -result : result;
  });
  return [...filled, ...rows.filter(empty)];
}
