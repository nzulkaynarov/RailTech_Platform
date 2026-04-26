import { useState, useEffect, useMemo, useCallback, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, Plus, ArrowUp, ArrowDown, ArrowUpDown, ChevronLeft, ChevronRight } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { TableHead } from '@/components/ui/table';
import { cn } from '@/lib/utils';

export type FilterOption = { value: string; label: string };

export type FilterSpec = {
  key: string;
  value: string;
  onChange: (v: string) => void;
  allLabel: string;
  options: FilterOption[];
  widthClass?: string;
};

interface ToolbarProps {
  searchValue: string;
  onSearchChange: (v: string) => void;
  searchPlaceholder?: string;
  filters?: FilterSpec[];
  newLabel?: string;
  onNew?: () => void;
  extra?: ReactNode;
}

export function Toolbar({
  searchValue, onSearchChange, searchPlaceholder,
  filters = [], newLabel, onNew, extra,
}: ToolbarProps) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
      <div className="relative flex-1">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder={searchPlaceholder ?? t('adminTable.search')}
          value={searchValue}
          onChange={(e) => onSearchChange(e.target.value)}
          className="pl-9"
        />
      </div>
      {filters.map((f) => (
        <Select key={f.key} value={f.value} onValueChange={f.onChange}>
          <SelectTrigger className={cn('w-full sm:w-52', f.widthClass)}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{f.allLabel}</SelectItem>
            {f.options.map((o) => (
              <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      ))}
      {extra}
      {onNew && (
        <Button onClick={onNew} className="gap-2">
          <Plus className="h-4 w-4" />
          {newLabel ?? t('adminTable.new')}
        </Button>
      )}
    </div>
  );
}

interface SortableHeadProps {
  sortKey: string;
  current: string;
  onChange: (k: string) => void;
  children: ReactNode;
  className?: string;
}

export function SortableHead({ sortKey, current, onChange, children, className }: SortableHeadProps) {
  const isAsc = current === sortKey;
  const isDesc = current === `-${sortKey}`;
  const icon = isAsc
    ? <ArrowUp className="h-3.5 w-3.5" />
    : isDesc
      ? <ArrowDown className="h-3.5 w-3.5" />
      : <ArrowUpDown className="h-3.5 w-3.5 opacity-40" />;
  return (
    <TableHead
      onClick={() => onChange(sortKey)}
      className={cn('cursor-pointer select-none hover:bg-accent/40', className)}
    >
      <span className="inline-flex items-center gap-1">
        {children}
        {icon}
      </span>
    </TableHead>
  );
}

interface PagerProps {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (p: number) => void;
}

export function Pager({ page, pageSize, total, onPageChange }: PagerProps) {
  const { t } = useTranslation();
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return null;
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  return (
    <div className="flex items-center justify-between p-3 text-sm text-muted-foreground">
      <span>{t('adminTable.showing', { from, to, total })}</span>
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          <ChevronLeft className="h-4 w-4" />
          {t('adminTable.prev')}
        </Button>
        <span className="tabular-nums">{page} / {totalPages}</span>
        <Button
          variant="ghost"
          size="sm"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
        >
          {t('adminTable.next')}
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

interface UseListParamsOptions {
  defaultOrdering?: string;
  pageSize?: number;
  debounceMs?: number;
}

export function useListParams<F extends Record<string, string> = Record<string, string>>(
  filterKeys: readonly (keyof F & string)[] = [],
  options: UseListParamsOptions = {},
) {
  const { defaultOrdering = '', pageSize = 20, debounceMs = 300 } = options;
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [filters, setFilters] = useState<Record<string, string>>(
    () => Object.fromEntries(filterKeys.map((k) => [k, 'all'])),
  );
  const [ordering, setOrdering] = useState(defaultOrdering);
  const [page, setPage] = useState(1);

  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput), debounceMs);
    return () => clearTimeout(id);
  }, [searchInput, debounceMs]);

  useEffect(() => {
    setPage(1);
  }, [search, filters, ordering]);

  const setFilter = useCallback((key: string, value: string) => {
    setFilters((f) => ({ ...f, [key]: value }));
  }, []);

  const toggleOrdering = useCallback((key: string) => {
    setOrdering((prev) => {
      if (prev === key) return `-${key}`;
      if (prev === `-${key}`) return '';
      return key;
    });
  }, []);

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
