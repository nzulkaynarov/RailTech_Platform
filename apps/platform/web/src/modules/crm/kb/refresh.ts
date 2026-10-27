import { useQueryClient } from "@tanstack/react-query";

/** Сброс кэша всех запросов базы знаний после действия: списки и открытая карточка перечитываются. */
export function useRefreshKb(): () => void {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      predicate: (query) => String(query.queryKey[0]).startsWith("/api/v1/crm/kb"),
    });
  };
}

/** Целое положительное из параметра адреса (`?doc=12`); всё прочее — `null`. */
export function parseId(value: string | null): number | null {
  if (value === null || !/^[1-9][0-9]{0,9}$/.test(value)) return null;
  return Number(value);
}

/** Параметры адреса с правками: `null` удаляет параметр. Остальные (`view`, `panel`) сохраняются. */
export function withParams(
  current: URLSearchParams,
  changes: Record<string, string | null>,
): string {
  const next = new URLSearchParams(current);
  for (const [key, value] of Object.entries(changes)) {
    if (value === null) next.delete(key);
    else next.set(key, value);
  }
  const text = next.toString();
  return text ? `?${text}` : "";
}

/** Ключ продукта допустим для CRM (пусто — без продукта). */
export function productKeyValid(value: string): boolean {
  return value === "" || /^[a-z0-9][a-z0-9-]{0,63}$/.test(value);
}

/** Предел файла в базе знаний — как в CRM (25 МБ). */
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
