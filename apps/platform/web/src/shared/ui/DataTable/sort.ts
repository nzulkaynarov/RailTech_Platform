import { useMemo } from "react";
import { useSearchParams } from "react-router";

/** Имя параметра адреса страницы: `?sort=field` — по возрастанию, `?sort=-field` — по убыванию. */
export const SORT_PARAM = "sort";

export type SortDir = "asc" | "desc";

export interface SortState {
  key: string;
  dir: SortDir;
}

/** Значение для сравнения; пустые (`null`, `undefined`, `""`, `NaN`) всегда идут в конец. */
export type SortValue = string | number | Date | null | undefined;

const KEY = /^[a-z][a-z0-9_]{0,39}$/;

/**
 * Разбор значения из адреса. Поле, которого нет в списке допустимых (столбцы с `sortKey`), отбрасывается: порядок по
 * произвольному имени из адреса недопустим ни на клиенте, ни на сервере.
 */
export function parseSort(
  raw: string | null | undefined,
  allowed: readonly string[],
): SortState | null {
  if (!raw) return null;
  const desc = raw.startsWith("-");
  const key = desc ? raw.slice(1) : raw;
  if (!KEY.test(key) || !allowed.includes(key)) return null;
  return { key, dir: desc ? "desc" : "asc" };
}

export function formatSort(sort: SortState | null): string | null {
  if (!sort) return null;
  return sort.dir === "desc" ? `-${sort.key}` : sort.key;
}

/** Щелчок по шапке: по возрастанию → по убыванию → снят. Другой столбец — сразу по возрастанию. */
export function nextSort(current: SortState | null, key: string): SortState | null {
  if (current?.key !== key) return { key, dir: "asc" };
  return current.dir === "asc" ? { key, dir: "desc" } : null;
}

function isEmpty(value: SortValue): boolean {
  if (value === null || value === undefined || value === "") return true;
  if (typeof value === "number") return Number.isNaN(value);
  if (value instanceof Date) return Number.isNaN(value.getTime());
  return false;
}

function comparable(value: SortValue): string | number {
  if (value instanceof Date) return value.getTime();
  return value as string | number;
}

/**
 * Стабильная сортировка на клиенте: текст — с учётом языка и чисел в строке («СЗ-2» перед «СЗ-10»), числа и даты — по
 * значению, пустые — в конце при любом направлении.
 */
export function sortRows<Row>(
  rows: readonly Row[],
  valueOf: (row: Row) => SortValue,
  dir: SortDir,
  locale: string,
): Row[] {
  const collator = new Intl.Collator(locale, { numeric: true, sensitivity: "base" });
  const sign = dir === "desc" ? -1 : 1;
  return rows
    .map((row, index) => ({ row, index, value: valueOf(row) }))
    .sort((a, b) => {
      const emptyA = isEmpty(a.value);
      const emptyB = isEmpty(b.value);
      if (emptyA || emptyB) {
        if (emptyA && emptyB) return a.index - b.index;
        return emptyA ? 1 : -1;
      }
      const x = comparable(a.value);
      const y = comparable(b.value);
      let result: number;
      if (typeof x === "number" && typeof y === "number") result = x - y;
      else result = collator.compare(String(x), String(y));
      return result === 0 ? a.index - b.index : result * sign;
    })
    .map((entry) => entry.row);
}

/**
 * Порядок из адреса страницы для постраничного списка: экран передаёт его серверу параметром `sort` (значение тоже
 * `field` / `-field`). Допустимые поля — те же, что объявлены столбцами `sortKey` (`undefined` — порядок по умолчанию).
 */
export function useSortParam(
  allowed: readonly string[],
  param: string = SORT_PARAM,
): string | undefined {
  const [params] = useSearchParams();
  const raw = params.get(param);
  const list = allowed.join(",");
  return useMemo(
    () => formatSort(parseSort(raw, list ? list.split(",") : [])) ?? undefined,
    [raw, list],
  );
}

/** Строки в порядке по значению столбца; без значения или направления — как пришли. */
export function useSortedRows<Row>(
  rows: readonly Row[],
  valueOf: ((row: Row) => SortValue) | undefined,
  dir: SortDir | undefined,
  locale: string,
): readonly Row[] {
  return useMemo(
    () => (valueOf && dir ? sortRows(rows, valueOf, dir, locale) : rows),
    [rows, valueOf, dir, locale],
  );
}
