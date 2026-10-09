import { useSearchParams } from "react-router";

import { type LeadFilters, leadFiltersToSearch, parseLeadFilters } from "./leadFilters";

/** Фильтры лидов из URL; изменение фильтра сбрасывает страницу на первую. */
export function useLeadFilters() {
  const [search, setSearch] = useSearchParams();
  const filters = parseLeadFilters(search);
  const update = (patch: Partial<LeadFilters>) => {
    const next = { ...filters, ...patch };
    if (!("page" in patch)) next.page = 1;
    setSearch(leadFiltersToSearch(next), { replace: true });
  };
  const reset = () => {
    setSearch(new URLSearchParams(), { replace: true });
  };
  return { filters, update, reset };
}
