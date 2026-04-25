import {
  ReactNode,
  useMemo,
  useState,
  useEffect,
  useCallback,
  useRef,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useUrlState } from '@/hooks/useUrlState';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Search,
  Columns,
  Download,
  MoreHorizontal,
  X,
  ChevronsUpDown,
  ChevronUp,
  ChevronDown,
  Rows3,
  Rows2,
} from 'lucide-react';
import { cn } from '@/lib/utils';

export interface AdminTableColumn<T> {
  id: string;
  header: ReactNode;
  /** Render a cell. If omitted, renders `(row as any)[id]`. */
  cell?: (row: T) => ReactNode;
  /** When present, enables sort toggle on this column (maps to ?ordering=). */
  sortKey?: string;
  className?: string;
  hideByDefault?: boolean;
  /** Disable the column-visibility toggle for this column (e.g. name column should always be visible). */
  alwaysVisible?: boolean;
}

export interface AdminTableTab {
  id: string;
  label: ReactNode;
  count?: number;
  /** Extra query params applied when this tab is active. */
  params?: Record<string, string | undefined>;
}

export interface AdminTableBulkAction<T> {
  id: string;
  label: ReactNode;
  variant?: 'default' | 'destructive' | 'secondary';
  /** Called with the selected rows. Should refetch/invalidate upstream. */
  onRun: (rows: T[]) => Promise<void> | void;
  disabled?: (rows: T[]) => boolean;
}

export interface AdminTableRowAction<T> {
  id: string;
  label: ReactNode;
  onRun: (row: T) => void;
  variant?: 'default' | 'destructive';
  icon?: ReactNode;
}

export interface AdminDataTableProps<T> {
  /** Namespaced URL query param prefix, so multiple tables on one page don't collide. */
  storageKey: string;
  rows: T[];
  getRowId: (row: T) => string | number;
  columns: AdminTableColumn<T>[];
  tabs?: AdminTableTab[];
  /** Called with current query state. Return the API promise. */
  isLoading?: boolean;
  /** Empty state — shown when rows.length === 0 and not loading. */
  emptyTitle?: ReactNode;
  emptyDescription?: ReactNode;
  emptyIcon?: ReactNode;
  /** Search placeholder. */
  searchPlaceholder?: string;
  /** Bulk actions — enable selection checkboxes. */
  bulkActions?: AdminTableBulkAction<T>[];
  /** Per-row actions inside the `⋯` kebab. */
  rowActions?: AdminTableRowAction<T>[];
  /** Click-row navigation target. */
  onRowClick?: (row: T) => void;
  /** Toolbar trailing content (primary CTA). */
  primaryAction?: ReactNode;
  /** Export endpoint base URL — triggers CSV/XLSX download via browser. */
  exportUrl?: string;
  /** Pagination: total, pageSize, onPageChange if server-driven. */
  pagination?: {
    total: number;
    page: number;
    pageSize: number;
    onPageChange: (page: number) => void;
  };
}

type Density = 'comfortable' | 'compact';

const QP_KEYS = {
  search: 'q',
  tab: 'tab',
  sort: 'sort',
  page: 'page',
} as const;

export function AdminDataTable<T>(props: AdminDataTableProps<T>): React.ReactNode {
  const { t } = useTranslation();
  const urlState = useUrlState();
  const {
    storageKey,
    rows,
    getRowId,
    columns,
    tabs,
    isLoading,
    emptyTitle,
    emptyDescription,
    emptyIcon,
    searchPlaceholder,
    bulkActions,
    rowActions,
    onRowClick,
    primaryAction,
    exportUrl,
    pagination,
  } = props;

  const ns = (k: string) => `${storageKey}.${k}`;

  const currentSearch = urlState.get(ns(QP_KEYS.search));
  const currentTab = urlState.get(ns(QP_KEYS.tab)) || (tabs?.[0]?.id ?? '');
  const currentSort = urlState.get(ns(QP_KEYS.sort));

  const [searchInput, setSearchInput] = useState(currentSearch);
  useEffect(() => setSearchInput(currentSearch), [currentSearch]);

  // Density preference (persisted in localStorage)
  const densityKey = `admin.${storageKey}.density`;
  const [density, setDensity] = useState<Density>(() => {
    try {
      return (localStorage.getItem(densityKey) as Density) || 'comfortable';
    } catch {
      return 'comfortable';
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(densityKey, density);
    } catch {
      /* ignore */
    }
  }, [density, densityKey]);

  // Column visibility preference (persisted)
  const columnsKey = `admin.${storageKey}.cols`;
  const [visibleCols, setVisibleCols] = useState<Record<string, boolean>>(() => {
    try {
      const raw = localStorage.getItem(columnsKey);
      if (raw) return JSON.parse(raw) as Record<string, boolean>;
    } catch {
      /* ignore */
    }
    const init: Record<string, boolean> = {};
    columns.forEach((c) => {
      init[c.id] = !c.hideByDefault;
    });
    return init;
  });
  useEffect(() => {
    try {
      localStorage.setItem(columnsKey, JSON.stringify(visibleCols));
    } catch {
      /* ignore */
    }
  }, [visibleCols, columnsKey]);

  const renderedColumns = useMemo(
    () => columns.filter((c) => c.alwaysVisible || visibleCols[c.id] !== false),
    [columns, visibleCols],
  );

  // Selection state
  const [selectedIds, setSelectedIds] = useState<Set<string | number>>(new Set());
  useEffect(() => {
    // clear selection when rows fundamentally change
    setSelectedIds((prev) => {
      const valid = new Set<string | number>();
      for (const row of rows) {
        const id = getRowId(row);
        if (prev.has(id)) valid.add(id);
      }
      return valid;
    });
  }, [rows, getRowId]);

  const selectedRows = useMemo(
    () => rows.filter((row) => selectedIds.has(getRowId(row))),
    [rows, selectedIds, getRowId],
  );

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const updateParam = useCallback(
    (key: string, value: string | null) => {
      urlState.set({ [`${storageKey}.${key}`]: value });
    },
    [urlState, storageKey],
  );

  function onSearchChange(v: string) {
    setSearchInput(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      updateParam(QP_KEYS.search, v);
      updateParam(QP_KEYS.page, null);
    }, 300);
  }

  function onTabChange(id: string) {
    updateParam(QP_KEYS.tab, id);
    updateParam(QP_KEYS.page, null);
    setSelectedIds(new Set());
  }

  function toggleSort(col: AdminTableColumn<T>) {
    if (!col.sortKey) return;
    const currentAsc = currentSort === col.sortKey;
    const currentDesc = currentSort === `-${col.sortKey}`;
    let next: string;
    if (!currentAsc && !currentDesc) next = col.sortKey;
    else if (currentAsc) next = `-${col.sortKey}`;
    else next = '';
    updateParam(QP_KEYS.sort, next || null);
  }

  function triggerExport(fmt: 'csv' | 'xlsx') {
    if (!exportUrl) return;
    const url = new URL(exportUrl, window.location.origin);
    // propagate current filters: search, tab-params, sort
    if (currentSearch) url.searchParams.set('search', currentSearch);
    if (currentSort) url.searchParams.set('ordering', currentSort);
    const activeTab = tabs?.find((t) => t.id === currentTab);
    if (activeTab?.params) {
      Object.entries(activeTab.params).forEach(([k, v]) => {
        if (v != null) url.searchParams.set(k, String(v));
      });
    }
    url.searchParams.set('fmt', fmt);
    window.open(url.toString(), '_blank', 'noopener');
  }

  // Visual density → cell padding
  const rowPad = density === 'compact' ? 'py-1.5' : 'py-2.5';

  // Is there an active selection? Show bulk toolbar above header.
  const hasSelection = selectedIds.size > 0;
  const allOnPageSelected =
    rows.length > 0 && rows.every((row) => selectedIds.has(getRowId(row)));

  function toggleRow(row: T) {
    const id = getRowId(row);
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function togglePage() {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) {
        rows.forEach((r) => next.delete(getRowId(r)));
      } else {
        rows.forEach((r) => next.add(getRowId(r)));
      }
      return next;
    });
  }

  function clearSelection() {
    setSelectedIds(new Set());
  }

  // Keyboard navigation — j/k to move focus between rows, Enter to open.
  const [focusIndex, setFocusIndex] = useState<number>(-1);
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement | null)?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'j') {
        e.preventDefault();
        setFocusIndex((i) => Math.min(rows.length - 1, i + 1));
      } else if (e.key === 'k') {
        e.preventDefault();
        setFocusIndex((i) => Math.max(0, i - 1));
      } else if (e.key === 'Enter' && focusIndex >= 0 && focusIndex < rows.length) {
        const row = rows[focusIndex];
        if (row && onRowClick) {
          e.preventDefault();
          onRowClick(row);
        }
      } else if (e.key === 'x' && focusIndex >= 0 && focusIndex < rows.length && bulkActions?.length) {
        const row = rows[focusIndex];
        if (row) {
          e.preventDefault();
          toggleRow(row);
        }
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, focusIndex, onRowClick, bulkActions]);

  return (
    <Card className="flex flex-col overflow-hidden">
      {/* Top: tabs + search + tools */}
      <div className="flex flex-col gap-2 border-b p-3 md:flex-row md:items-center">
        {tabs && tabs.length > 0 ? (
          <Tabs value={currentTab} onValueChange={onTabChange} className="min-w-0">
            <TabsList className="h-8">
              {tabs.map((tab) => (
                <TabsTrigger key={tab.id} value={tab.id} className="text-xs">
                  {tab.label}
                  {typeof tab.count === 'number' ? (
                    <Badge variant="secondary" className="ml-1.5 h-4 px-1 text-xs">
                      {tab.count}
                    </Badge>
                  ) : null}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        ) : null}

        <div className="relative flex-1 md:max-w-sm">
          <Search className="pointer-events-none absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            type="search"
            value={searchInput}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={searchPlaceholder ?? t('common.search')}
            className="h-8 pl-7 text-xs"
          />
          {searchInput ? (
            <button
              type="button"
              onClick={() => onSearchChange('')}
              className="absolute right-1.5 top-1.5 rounded-full p-0.5 text-muted-foreground hover:bg-muted"
              aria-label={t('common.clear')}
            >
              <X className="h-3 w-3" />
            </button>
          ) : null}
        </div>

        <div className="flex items-center gap-1 md:ml-auto">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="h-8 gap-1 px-2 text-xs" aria-label={t('adminTable.columns')}>
                <Columns className="h-3.5 w-3.5" />
                <span className="hidden md:inline">{t('adminTable.columns')}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-52">
              <DropdownMenuLabel className="text-xs">{t('adminTable.columns')}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {columns.map((c) => (
                <DropdownMenuCheckboxItem
                  key={c.id}
                  checked={c.alwaysVisible || visibleCols[c.id] !== false}
                  disabled={c.alwaysVisible}
                  onCheckedChange={(v) =>
                    setVisibleCols((prev) => ({ ...prev, [c.id]: Boolean(v) }))
                  }
                  className="text-xs"
                >
                  {c.header}
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-8 p-0"
            onClick={() => setDensity((d) => (d === 'comfortable' ? 'compact' : 'comfortable'))}
            aria-label={t('adminTable.density')}
          >
            {density === 'comfortable' ? (
              <Rows3 className="h-3.5 w-3.5" />
            ) : (
              <Rows2 className="h-3.5 w-3.5" />
            )}
          </Button>

          {exportUrl ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="h-8 gap-1 px-2 text-xs" aria-label={t('adminTable.export')}>
                  <Download className="h-3.5 w-3.5" />
                  <span className="hidden md:inline">{t('adminTable.export')}</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem className="text-xs" onClick={() => triggerExport('xlsx')}>
                  {t('adminTable.exportXlsx')}
                </DropdownMenuItem>
                <DropdownMenuItem className="text-xs" onClick={() => triggerExport('csv')}>
                  {t('adminTable.exportCsv')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}

          {primaryAction}
        </div>
      </div>

      {/* Bulk toolbar */}
      {hasSelection && bulkActions && bulkActions.length > 0 ? (
        <div className="flex items-center gap-2 border-b bg-accent/50 px-3 py-2 text-xs">
          <span className="font-medium">
            {t('adminTable.selected', { count: selectedIds.size })}
          </span>
          <div className="ml-auto flex items-center gap-1">
            {bulkActions.map((action) => (
              <Button
                key={action.id}
                size="sm"
                variant={action.variant ?? 'secondary'}
                className="h-7 text-xs"
                disabled={action.disabled?.(selectedRows) ?? false}
                onClick={async () => {
                  try {
                    await action.onRun(selectedRows);
                    clearSelection();
                  } catch {
                    /* surfaced by action itself */
                  }
                }}
              >
                {action.label}
              </Button>
            ))}
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={clearSelection}>
              {t('common.clear')}
            </Button>
          </div>
        </div>
      ) : null}

      {/* Table */}
      <div className="overflow-x-auto">
        <Table className="min-w-full">
          <TableHeader>
            <TableRow>
              {bulkActions && bulkActions.length > 0 ? (
                <TableHead className="w-8">
                  <Checkbox
                    checked={allOnPageSelected}
                    onCheckedChange={togglePage}
                    aria-label={t('adminTable.selectAll')}
                  />
                </TableHead>
              ) : null}
              {renderedColumns.map((c) => {
                const isSorted = currentSort === c.sortKey;
                const isSortedDesc = currentSort === `-${c.sortKey}`;
                return (
                  <TableHead
                    key={c.id}
                    className={cn('text-xs font-medium', c.className, c.sortKey && 'cursor-pointer select-none')}
                    onClick={() => toggleSort(c)}
                  >
                    <span className="inline-flex items-center gap-1">
                      {c.header}
                      {c.sortKey ? (
                        isSorted ? (
                          <ChevronUp className="h-3 w-3" />
                        ) : isSortedDesc ? (
                          <ChevronDown className="h-3 w-3" />
                        ) : (
                          <ChevronsUpDown className="h-3 w-3 text-muted-foreground" />
                        )
                      ) : null}
                    </span>
                  </TableHead>
                );
              })}
              {rowActions && rowActions.length > 0 ? <TableHead className="w-10" /> : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && rows.length === 0 ? (
              Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={`sk-${i}`}>
                  {bulkActions ? <TableCell className="w-8" /> : null}
                  {renderedColumns.map((c) => (
                    <TableCell key={c.id} className={cn('text-xs', rowPad)}>
                      <Skeleton className="h-3 w-full" />
                    </TableCell>
                  ))}
                  {rowActions ? <TableCell /> : null}
                </TableRow>
              ))
            ) : rows.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={
                    renderedColumns.length +
                    (bulkActions ? 1 : 0) +
                    (rowActions ? 1 : 0)
                  }
                  className="py-10 text-center text-xs text-muted-foreground"
                >
                  <div className="flex flex-col items-center gap-2">
                    {emptyIcon}
                    <div className="font-medium">{emptyTitle ?? t('adminTable.empty')}</div>
                    {emptyDescription ? <div>{emptyDescription}</div> : null}
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row, idx) => {
                const id = getRowId(row);
                const isSelected = selectedIds.has(id);
                const isFocused = idx === focusIndex;
                return (
                  <TableRow
                    key={String(id)}
                    data-selected={isSelected || undefined}
                    data-focused={isFocused || undefined}
                    className={cn(
                      'cursor-pointer text-xs transition-colors',
                      isSelected && 'bg-accent/40',
                      isFocused && 'ring-1 ring-primary/50 ring-inset',
                    )}
                    onClick={(e) => {
                      const target = e.target as HTMLElement;
                      // Avoid row-click when interacting with row controls
                      if (target.closest('[data-row-action]')) return;
                      if (target.closest('[data-checkbox]')) return;
                      onRowClick?.(row);
                    }}
                  >
                    {bulkActions && bulkActions.length > 0 ? (
                      <TableCell className={cn('w-8', rowPad)} data-checkbox>
                        <Checkbox
                          checked={isSelected}
                          onCheckedChange={() => toggleRow(row)}
                          aria-label={t('adminTable.selectRow')}
                          onClick={(e) => e.stopPropagation()}
                        />
                      </TableCell>
                    ) : null}
                    {renderedColumns.map((c) => (
                      <TableCell key={c.id} className={cn(rowPad, c.className)}>
                        {c.cell ? c.cell(row) : String((row as Record<string, unknown>)[c.id] ?? '')}
                      </TableCell>
                    ))}
                    {rowActions && rowActions.length > 0 ? (
                      <TableCell className={cn('w-10 text-right', rowPad)} data-row-action>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7"
                              aria-label={t('adminTable.rowActions')}
                            >
                              <MoreHorizontal className="h-3.5 w-3.5" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {rowActions.map((action) => (
                              <DropdownMenuItem
                                key={action.id}
                                className={cn('text-xs', action.variant === 'destructive' && 'text-destructive')}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  action.onRun(row);
                                }}
                              >
                                {action.icon ? <span className="mr-1.5">{action.icon}</span> : null}
                                {action.label}
                              </DropdownMenuItem>
                            ))}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </TableCell>
                    ) : null}
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
      {pagination && pagination.total > pagination.pageSize ? (
        <div className="flex items-center justify-between border-t px-3 py-2 text-xs text-muted-foreground">
          <span>
            {t('adminTable.paginationLabel', {
              from: (pagination.page - 1) * pagination.pageSize + 1,
              to: Math.min(pagination.page * pagination.pageSize, pagination.total),
              total: pagination.total,
            })}
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs"
              disabled={pagination.page <= 1}
              onClick={() => {
                pagination.onPageChange(pagination.page - 1);
                updateParam(QP_KEYS.page, String(pagination.page - 1));
              }}
            >
              {t('common.prev')}
            </Button>
            <span>
              {pagination.page} / {Math.max(1, Math.ceil(pagination.total / pagination.pageSize))}
            </span>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs"
              disabled={pagination.page * pagination.pageSize >= pagination.total}
              onClick={() => {
                pagination.onPageChange(pagination.page + 1);
                updateParam(QP_KEYS.page, String(pagination.page + 1));
              }}
            >
              {t('common.next')}
            </Button>
          </div>
        </div>
      ) : null}
    </Card>
  );
}

/**
 * Small hook for pages that want to read current query state (tab / search / sort)
 * without duplicating the storage-key namespacing convention.
 */
export function useAdminTableQueryState(storageKey: string) {
  const urlState = useUrlState();
  const p = (k: keyof typeof QP_KEYS) => urlState.get(`${storageKey}.${QP_KEYS[k]}`);
  return {
    search: p('search'),
    tab: p('tab'),
    sort: p('sort'),
    page: Number(p('page') || '1') || 1,
  };
}
