/**
 * Фильтры списка лидов живут в URL (аудит UI U-05): «Назад» из карточки возвращает
 * тот же список, ссылку можно отправить коллеге, дашборд ведёт на отфильтрованный список.
 */
import type { ListLeadsParams } from "../api/generated/model";

export const LEADS_PAGE = 50;
export const LEAD_SORTS = ["last_message", "score", "created"] as const;

export type LeadFilters = {
  q?: string | undefined;
  stage?: string | undefined;
  owner?: string | undefined;
  language?: string | undefined;
  min_score?: number | undefined;
  from?: string | undefined; // YYYY-MM-DD, начало дня по Ташкенту
  to?: string | undefined; // YYYY-MM-DD включительно
  sort?: string | undefined;
  page: number;
};

const text = (search: URLSearchParams, key: string): string | undefined =>
  search.get(key)?.trim() || undefined;

const DATE = /^\d{4}-\d{2}-\d{2}$/;

export function parseLeadFilters(search: URLSearchParams): LeadFilters {
  const score = Number(search.get("min_score"));
  const page = Number(search.get("page"));
  const sort = text(search, "sort");
  const from = text(search, "from");
  const to = text(search, "to");
  return {
    q: text(search, "q"),
    stage: text(search, "stage"),
    owner: text(search, "owner"),
    language: text(search, "language"),
    min_score: search.has("min_score") && score >= 0 && score <= 100 ? score : undefined,
    from: from && DATE.test(from) ? from : undefined,
    to: to && DATE.test(to) ? to : undefined,
    sort: sort && (LEAD_SORTS as readonly string[]).includes(sort) ? sort : undefined,
    page: Number.isInteger(page) && page > 1 ? page : 1,
  };
}

export function leadFiltersToSearch(filters: LeadFilters): URLSearchParams {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === "" || (key === "page" && value === 1)) continue;
    search.set(key, String(value));
  }
  return search;
}

/** День YYYY-MM-DD → ISO начала дня в Ташкенте (UTC+5, без перехода на летнее время). */
const tashkentDayStart = (day: string): string => `${day}T00:00:00+05:00`;

function nextDay(day: string): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

/** Параметры API по фильтрам из URL. */
export function toListParams(filters: LeadFilters): ListLeadsParams {
  return {
    q: filters.q ?? null,
    stage: filters.stage ?? null,
    owner: filters.owner ?? null,
    language: filters.language ?? null,
    min_score: filters.min_score ?? null,
    created_from: filters.from ? tashkentDayStart(filters.from) : null,
    created_to: filters.to ? tashkentDayStart(nextDay(filters.to)) : null,
    sort: filters.sort ?? "last_message",
    limit: LEADS_PAGE,
    offset: (filters.page - 1) * LEADS_PAGE,
  };
}

/** Сколько фильтров включено (сортировка и страница — не фильтры; период — один фильтр). */
export function activeFilterCount(f: LeadFilters): number {
  const flags = [f.q, f.stage, f.owner, f.language, f.min_score, f.from ?? f.to];
  return flags.filter((v) => v !== undefined && v !== "").length;
}
