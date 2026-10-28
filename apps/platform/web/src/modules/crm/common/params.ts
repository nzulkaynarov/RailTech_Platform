import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router";

/** Правка параметров адреса без новой записи в истории: `null` удаляет параметр, остальные сохраняются. */
export function useParamChanger(): (changes: Record<string, string | null>) => void {
  const [, setParams] = useSearchParams();
  return (changes) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(changes)) {
          if (value === null) next.delete(key);
          else next.set(key, value);
        }
        return next;
      },
      { replace: true },
    );
  };
}

/** Адрес с правками параметров (`null` удаляет параметр). */
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

const LEAD = /^L-\d{4,}$/;

/** Номер лида из адреса (`L-2041`, регистр не важен); всё прочее — `null`. */
export function parseLead(value: string | null | undefined): string | null {
  const upper = value?.toUpperCase() ?? null;
  return upper && LEAD.test(upper) ? upper : null;
}

/** Id клиента из адреса; всё, что не положительное целое, — `null`. */
export function parseClientId(value: string | null | undefined): number | null {
  if (!value || !/^\d{1,9}$/.test(value)) return null;
  const id = Number(value);
  return id > 0 ? id : null;
}

/** Адрес карточки клиента в боковом окне (тот же, что у поиска ⌘K). */
export function clientPath(id: number): string {
  return `/crm/clients/${String(id)}?panel=open&tab=card`;
}

/** Сброс кэша CRM после действия: списки лидов, клиентов и открытые карточки перечитываются. */
export function useRefreshCrm(): () => void {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      predicate: (query) => String(query.queryKey[0]).startsWith("/api/v1/crm/"),
    });
  };
}
