/**
 * Состояние и вычисления списков (поиск, фильтры, сортировка, страница) — ОТДЕЛЬНО от
 * компонентов таблицы. Разделение не косметика: файл, экспортирующий и компоненты, и хуки,
 * ломает Fast Refresh в Vite dev-сервере (react-refresh/only-export-components), а dev-сервер
 * в проекте используется (Docs/dev/ops/docker-setup.md).
 */

import { useState, useEffect, useMemo, useCallback } from 'react';

import { useUrlState } from '@/hooks/useUrlState';

interface UseListParamsOptions {
  defaultOrdering?: string;
  pageSize?: number;
  debounceMs?: number;
  /** Пространство имён состояния списка в АДРЕСЕ.
   *
   *  Без него состояние живёт только в памяти компонента: F5 сбрасывает поиск, фильтры,
   *  сортировку и страницу, а ссылка, посланная коллеге, открывает не тот экран, что видел
   *  отправитель (замер 26-08, находка 81). Эталон один и тот же у Odoo (фильтры в hash) и
   *  Salesforce (list view в URL): состояние списка адресуемо.
   *
   *  Ключ обязателен именно как ПРОСТРАНСТВО ИМЁН: на одном экране бывает несколько списков,
   *  и без разделения они затирали бы состояние друг друга. */
  urlKey?: string;
}

export function useListParams<F extends Record<string, string> = Record<string, string>>(
  filterKeys: readonly (keyof F & string)[] = [],
  options: UseListParamsOptions = {},
) {
  const { defaultOrdering = '', pageSize = 20, debounceMs = 300, urlKey } = options;
  const { set: setUrl } = useUrlState();
  // Читаем адрес ОДИН раз при монтировании: дальше состояние ведёт компонент, а адрес лишь
  // отражает его. Иначе каждое нажатие клавиши в поиске перезапускало бы разбор URL.
  const [initial] = useState(() => {
    if (!urlKey) return null;
    const read = (key: string) => new URLSearchParams(window.location.search).get(`${urlKey}.${key}`) ?? '';
    return {
      search: read('q'),
      ordering: read('sort'),
      page: Number(read('page') || '1') || 1,
      filters: Object.fromEntries(filterKeys.map((k) => [k, read(`f_${k}`) || 'all'])),
    };
  });
  const [searchInput, setSearchInput] = useState(initial?.search ?? '');
  const [search, setSearch] = useState(initial?.search ?? '');
  const [filters, setFilters] = useState<Record<string, string>>(
    () => initial?.filters ?? Object.fromEntries(filterKeys.map((k) => [k, 'all'])),
  );
  const [ordering, setOrdering] = useState(initial?.ordering || defaultOrdering);
  const [page, setPage] = useState(initial?.page ?? 1);

  useEffect(() => {
    const id = setTimeout(() => {
      // Применение поиска и сброс страницы — одно событие (см. комментарий у setFilter ниже).
      // Эффект просыпается только на смену ввода, поэтому лишних сбросов страницы нет.
      setSearch(searchInput);
      setPage(1);
    }, debounceMs);
    return () => clearTimeout(id);
  }, [searchInput, debounceMs]);

  // Страница обнуляется ВМЕСТЕ со сменой выборки, одним событием. Раньше это делал эффект
  // ПОСЛЕ коммита: у реестров с серверной постраничкой (MyProductsPage, ProductManagement)
  // уходил запрос с новым поиском и СТАРОЙ страницей — пользователь видел кадр «Ничего не
  // найдено», затем летел второй запрос уже с page=1. Два похода в бэкенд на каждую смену
  // поиска/фильтра/сортировки. Найдено триажем правил React Compiler 18-08.
  const setFilter = useCallback((key: string, value: string) => {
    setFilters((f) => ({ ...f, [key]: value }));
    setPage(1);
  }, []);

  const toggleOrdering = useCallback((key: string) => {
    setOrdering((prev) => {
      if (prev === key) return `-${key}`;
      if (prev === `-${key}`) return '';
      return key;
    });
    setPage(1);
  }, []);

  // Отражаем состояние в адрес. Отдельным эффектом, а не внутри сеттеров: сеттеров пять, и
  // повторять запись в каждом — тот самый класс «одна механика в нескольких местах».
  // `urlState.set` сам не трогает историю, если ничего не изменилось.
  useEffect(() => {
    if (!urlKey) return;
    setUrl({
      [`${urlKey}.q`]: search || null,
      [`${urlKey}.sort`]: ordering && ordering !== defaultOrdering ? ordering : null,
      [`${urlKey}.page`]: page > 1 ? String(page) : null,
      ...Object.fromEntries(
        Object.entries(filters).map(([key, value]) => [`${urlKey}.f_${key}`, value && value !== 'all' ? value : null]),
      ),
    });
    // Зависим от СТАБИЛЬНОГО `set` (он обёрнут `useCallback`), а не от объекта `urlState`:
    // объект новый на каждый рендер, и эффект просыпался бы вхолостую после каждой
    // перерисовки.
  }, [urlKey, setUrl, search, ordering, page, filters, defaultOrdering]);

  return {
    searchInput, setSearchInput,
    search,
    filters, setFilter,
    ordering, toggleOrdering,
    page, setPage,
    pageSize,
  };
}

export function applyListParams<T>(
  items: T[],
  params: {
    search: string;
    filters: Record<string, string>;
    ordering: string;
    page: number;
    pageSize: number;
  },
  spec: {
    searchFields: (item: T) => (string | number | null | undefined)[];
    filterPredicates?: Record<string, (item: T, value: string) => boolean>;
    sortAccessors?: Record<string, (item: T) => string | number | null | undefined>;
  },
): { items: T[]; total: number } {
  const searchQuery = params.search.trim().toLowerCase();
  let result = items;

  if (searchQuery) {
    result = result.filter((it) =>
      spec.searchFields(it).some((v) => (v ?? '').toString().toLowerCase().includes(searchQuery)),
    );
  }

  Object.entries(params.filters).forEach(([key, value]) => {
    if (value === 'all' || !value) return;
    const pred = spec.filterPredicates?.[key];
    if (pred) result = result.filter((it) => pred(it, value));
  });

  if (params.ordering) {
    const desc = params.ordering.startsWith('-');
    const key = desc ? params.ordering.slice(1) : params.ordering;
    const acc = spec.sortAccessors?.[key];
    if (acc) {
      result = [...result].sort((a, b) => {
        const va = acc(a);
        const vb = acc(b);
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        const cmp = typeof va === 'number' && typeof vb === 'number'
          ? va - vb
          : String(va).localeCompare(String(vb));
        return desc ? -cmp : cmp;
      });
    }
  }

  const total = result.length;
  const start = (params.page - 1) * params.pageSize;
  const paged = result.slice(start, start + params.pageSize);
  return { items: paged, total };
}

export function useDebouncedValue<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

export function paginate<T>(items: T[], page: number, pageSize: number): { items: T[]; total: number } {
  const start = (page - 1) * pageSize;
  return { items: items.slice(start, start + pageSize), total: items.length };
}

export function useStaticMemo<T>(factory: () => T, deps: unknown[]): T {
  return useMemo(factory, deps); // eslint-disable-line react-hooks/exhaustive-deps
}
