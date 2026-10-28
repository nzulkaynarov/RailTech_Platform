import { useQueryClient } from "@tanstack/react-query";

/**
 * Сброс кэша всех запросов документов EDS после действия: списки и открытая карточка перечитываются. Вместе с ними — «Моя очередь»
 * и бейджи меню: отправленный на согласование документ перестаёт быть делом автора («Доработать», D1-6b), не дожидаясь подсказки
 * потока или опроса.
 */
export function useRefreshDocuments(): () => void {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      predicate: (query) => {
        const key = String(query.queryKey[0]);
        return (
          key.startsWith("/api/v1/eds/documents") ||
          key === "/api/v1/menu-counters" ||
          key.startsWith("/api/v1/queue")
        );
      },
    });
  };
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Id документа EDS из параметра адреса (`?doc=…`); всё прочее — `null`. */
export function parseDocumentId(value: string | null): string | null {
  return value !== null && UUID.test(value) ? value.toLowerCase() : null;
}

/** Параметры адреса с правками: `null` удаляет параметр. Остальные (`scope`, `kind`) сохраняются. */
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
