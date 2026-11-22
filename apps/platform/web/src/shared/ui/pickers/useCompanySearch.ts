import { useSearchCounterparties } from "../../api/generated/platform-bff";
import type { CounterpartyPick, CounterpartyPickRole } from "../../api/generated/model";
import { useDebounced } from "../../lib/useDebounced";

/** Сколько строк просим у поиска — как в контракте `GET /people/counterparties` (по умолчанию 10, максимум 20) */
const LIMIT = 10;

/**
 * Единый поиск контрагентов для поля выбора компании (ЕД-6): ввод обрезается и задерживается на 300 мс, пустой ввод
 * показывает первые строки (роль формы поднимает свои выше). Пока список закрыт, запрос не идёт.
 */
export function useCompanySearch(
  search: string,
  role: CounterpartyPickRole | undefined,
  open: boolean,
): { items: CounterpartyPick[]; query: string; loading: boolean; settled: boolean } {
  const query = useDebounced(search.trim());
  const found = useSearchCounterparties(
    { q: query || undefined, role, limit: LIMIT },
    { query: { enabled: open, staleTime: 30_000, retry: false } },
  );
  return {
    items: open ? (found.data?.items ?? []) : [],
    query,
    loading: found.isFetching || query !== search.trim(),
    settled: found.isSuccess && query === search.trim(),
  };
}
