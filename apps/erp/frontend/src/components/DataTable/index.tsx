import { ReactNode } from 'react';
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
  /** Поле сортировки. Пусто/не задано — колонка НЕ сортируется, и это видно. */
  sortKey?: string;
  current?: string;
  onChange?: (k: string) => void;
  children: ReactNode;
  className?: string;
}

export function SortableHead({ sortKey, current = '', onChange, children, className }: SortableHeadProps) {
  // Заголовок без поля сортировки рисовался ровно как сортируемый — курсор-указатель и
  // стрелки, — но клик по нему не делал ничего. Пять колонок обещали сортировку, которой
  // нет (аудит UI 2026-07-30). Теперь несортируемая колонка выглядит несортируемой.
  if (!sortKey || !onChange) {
    return <TableHead className={className}>{children}</TableHead>;
  }
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
