import { type ReactNode } from 'react';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { SortableHead } from '@/components/DataTable';
import { cn } from '@/lib/utils';
import { clickOriginatesFromControl } from '@/lib/rowClick';

export interface ResponsiveColumn<T> {
  id: string;
  /** Column header (already translated) — also the default mobile label. */
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** DB sort key — with `sorting` set on the table, the desktop header becomes sortable. */
  sortKey?: string;
  /** Extra classes for the desktop header + cell (e.g. 'text-right', 'w-10'). */
  className?: string;
  /** Mobile card label (already translated). Omit to reuse `header`. */
  mobileLabel?: ReactNode;
  /** Render this cell as a prominent full-width heading atop the mobile row (part of the row click). */
  mobileTitle?: boolean;
  /** Full-width interactive region at the bottom of the mobile row (e.g. an actions menu); stops row-click bubbling. */
  mobileActions?: boolean;
  /** Drop this column from the mobile row entirely (e.g. a redundant open-affordance when the row is clickable). */
  mobileHidden?: boolean;
}

export interface ResponsiveDataTableProps<T> {
  columns: ResponsiveColumn<T>[];
  rows: T[];
  getRowId: (row: T) => string | number;
  onRowClick?: (row: T) => void;
  /** Wire the sortable headers to the list's ordering state. */
  sorting?: { ordering: string; onToggle: (key: string) => void };
  rowClassName?: (row: T) => string;
}

/**
 * Renders a shadcn <Table> at sm+ and a divided label:value list below sm, so wide data
 * tables read as stacked rows on phones instead of clipping inside a horizontal scroller.
 * shadcn primitives + semantic tokens only; the mobile list is designed to sit inside the
 * page's existing <Card><CardContent className="p-0"> wrapper (no nested cards).
 */
export function ResponsiveDataTable<T>({
  columns, rows, getRowId, onRowClick, sorting, rowClassName,
}: ResponsiveDataTableProps<T>) {
  return (
    <>
      {/* Desktop — full table at sm and up */}
      <div className="hidden sm:block">
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((col) =>
                col.sortKey && sorting ? (
                  <SortableHead
                    key={col.id}
                    sortKey={col.sortKey}
                    current={sorting.ordering}
                    onChange={sorting.onToggle}
                    className={col.className}
                  >
                    {col.header}
                  </SortableHead>
                ) : (
                  <TableHead key={col.id} className={col.className}>
                    {col.header}
                  </TableHead>
                ),
              )}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow
                key={getRowId(row)}
                role={onRowClick ? 'button' : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                className={cn(
                  onRowClick && 'cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
                  rowClassName?.(row),
                )}
                // Open the document on row click — but never steal a click that landed on a control
                // inside the row (its actions menu / link owns that click). Same guard as the raw pages.
                onClick={onRowClick ? (event) => { if (!clickOriginatesFromControl(event.target)) onRowClick(row); } : undefined}
                onKeyDown={onRowClick ? (event) => {
                  if (event.target !== event.currentTarget) return;
                  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onRowClick(row); }
                } : undefined}
              >
                {columns.map((col) => (
                  <TableCell key={col.id} className={col.className}>
                    {col.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* Mobile — divided stack of label:value rows below sm */}
      <div className="divide-y sm:hidden">
        {rows.map((row) => {
          const visible = columns.filter((col) => !col.mobileHidden);
          return (
            <div
              key={getRowId(row)}
              // Клавиатура работала только на десктопной половине: мобильная карточка была
              // обычным div с onClick — без роли, без фокуса и без Enter/Space. Правило
              // проекта «строки списка доступны с клавиатуры» распространяется на ОБЕ
              // раскладки: мобильная — не декорация, а тот же список на узком экране.
              role={onRowClick ? 'button' : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              className={cn(
                'flex flex-col gap-2 p-4',
                onRowClick && 'cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
                rowClassName?.(row),
              )}
              // N4 (мобильный аудит «Номенклатуры»): тот же гард, что у десктопной строки, —
              // тап по чекбоксу или кнопке внутри карточки не должен заодно открывать строку.
              onClick={onRowClick ? (event) => { if (!clickOriginatesFromControl(event.target)) onRowClick(row); } : undefined}
              onKeyDown={onRowClick ? (event) => {
                if (event.target !== event.currentTarget) return;
                if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onRowClick(row); }
              } : undefined}
            >
              {visible.map((col) => {
                if (col.mobileTitle) {
                  return (
                    <div key={col.id} className="text-sm font-medium">
                      {col.cell(row)}
                    </div>
                  );
                }
                if (col.mobileActions) {
                  return (
                    <div
                      key={col.id}
                      className="flex justify-end border-t pt-2"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {col.cell(row)}
                    </div>
                  );
                }
                return (
                  <div key={col.id} className="flex items-baseline justify-between gap-3">
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {col.mobileLabel ?? col.header}
                    </span>
                    <span className="min-w-0 text-right text-sm">{col.cell(row)}</span>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </>
  );
}
