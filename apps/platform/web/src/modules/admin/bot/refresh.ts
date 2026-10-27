import { useQueryClient } from "@tanstack/react-query";

/** Сброс кэша запросов «Настроек бота» после действия: настройки, шаблоны перечитываются. */
export function useRefreshBot(): () => Promise<void> {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({
      predicate: (query) => String(query.queryKey[0]).startsWith("/api/v1/admin/bot"),
    });
}

/** Целое положительное из параметра адреса; всё прочее — `null`. */
export function parseId(value: string | null): number | null {
  if (value === null || !/^[1-9][0-9]{0,9}$/.test(value)) return null;
  return Number(value);
}

/** Параметры адреса с правками: `null` удаляет параметр. */
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
