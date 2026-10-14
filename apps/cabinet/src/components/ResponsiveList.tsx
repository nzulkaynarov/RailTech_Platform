import type { MouseEvent, ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { DESKTOP_QUERY, useMediaQuery } from '@/hooks/useMediaQuery';
import { cn } from '@/lib/utils';

/**
 * Адаптивный список (по образцу B2B `ResponsiveDataTable`): таблица от `lg`, ниже — карточки
 * «подпись: значение», чтобы на 390 px ничего не уезжало вбок. Отрисовывается одна раскладка
 * (media-запрос), а не обе со скрытием — в дереве доступности нет дублей.
 *
 * Клавиатура: строка открывается настоящей ссылкой в заголовке (`rowHref`) — Tab + Enter; клик мышью
 * по любой части строки ведёт туда же (кроме кликов по кнопкам и ссылкам внутри). На карточке ссылка
 * растянута на всю карточку, действия лежат поверх неё.
 */
export interface ListColumn<T> {
  id: string;
  header: string;
  cell: (row: T) => ReactNode;
  /** Классы ячейки и заголовка таблицы (`text-right`, ширина). */
  className?: string;
  /** Не показывать в карточке телефона (например, повтор заголовка). */
  mobileHidden?: boolean;
}

export interface ResponsiveListProps<T> {
  /** Подпись списка для экранных дикторов (`aria-label` таблицы / списка карточек). */
  label: string;
  rows: T[];
  getRowId: (row: T) => string | number;
  /** Заголовок строки: первая колонка таблицы и шапка карточки. */
  title: { header: string; cell: (row: T) => ReactNode };
  /** Куда ведёт строка; без него строка не кликабельна. */
  rowHref?: (row: T) => string;
  columns: ListColumn<T>[];
  /** Действия строки (кнопки) — последняя колонка таблицы и низ карточки. */
  actions?: { header: string; cell: (row: T) => ReactNode };
  rowClassName?: (row: T) => string | undefined;
}

const INTERACTIVE = 'a, button, input, select, textarea, label, [role="button"], [role="checkbox"]';

function fromControl(event: MouseEvent): boolean {
  const target = event.target as Element | null;
  const control = target?.closest(INTERACTIVE);
  return Boolean(control && control !== event.currentTarget);
}

export function ResponsiveList<T>(props: ResponsiveListProps<T>) {
  const desktop = useMediaQuery(DESKTOP_QUERY);
  return desktop ? <DesktopTable {...props} /> : <MobileCards {...props} />;
}

function TitleLink({ href, children, stretched }: { href?: string; children: ReactNode; stretched?: boolean }) {
  if (!href) return <>{children}</>;
  return (
    <Link
      to={href}
      className={cn(
        'rounded-sm font-medium text-foreground underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring',
        stretched && 'after:absolute after:inset-0 after:rounded-lg after:content-[""] focus-visible:ring-0 focus-visible:after:ring-2 focus-visible:after:ring-ring',
      )}
    >
      {children}
    </Link>
  );
}

function DesktopTable<T>({ label, rows, getRowId, title, rowHref, columns, actions, rowClassName }: ResponsiveListProps<T>) {
  const navigate = useNavigate();
  return (
    <div className="rounded-lg border bg-card">
      <Table aria-label={label}>
        <TableHeader>
          <TableRow>
            <TableHead>{title.header}</TableHead>
            {columns.map((column) => (
              <TableHead key={column.id} className={column.className}>
                {column.header}
              </TableHead>
            ))}
            {actions ? <TableHead className="text-right">{actions.header}</TableHead> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const href = rowHref?.(row);
            return (
              <TableRow
                key={getRowId(row)}
                className={cn(href && 'cursor-pointer', rowClassName?.(row))}
                onClick={href ? (event) => !fromControl(event) && navigate(href) : undefined}
              >
                <TableCell className="min-w-48 whitespace-normal">
                  <TitleLink href={href}>{title.cell(row)}</TitleLink>
                </TableCell>
                {columns.map((column) => (
                  <TableCell key={column.id} className={column.className}>
                    {column.cell(row)}
                  </TableCell>
                ))}
                {actions ? (
                  <TableCell className="text-right">
                    <div className="flex flex-wrap justify-end gap-2">{actions.cell(row)}</div>
                  </TableCell>
                ) : null}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function MobileCards<T>({ label, rows, getRowId, title, rowHref, columns, actions, rowClassName }: ResponsiveListProps<T>) {
  return (
    <ul aria-label={label} className="flex flex-col gap-3">
      {rows.map((row) => {
        const href = rowHref?.(row);
        const actionNodes = actions?.cell(row);
        return (
          <li
            key={getRowId(row)}
            className={cn('relative flex min-w-0 flex-col gap-2 rounded-lg border bg-card p-4', rowClassName?.(row))}
          >
            <div className="min-w-0 text-sm break-words">
              <TitleLink href={href} stretched>
                {title.cell(row)}
              </TitleLink>
            </div>
            {columns
              .filter((column) => !column.mobileHidden)
              .map((column) => (
                <div key={column.id} className="flex min-w-0 items-baseline justify-between gap-3">
                  <span className="shrink-0 text-xs text-muted-foreground">{column.header}</span>
                  <span className="min-w-0 text-right text-sm break-words">{column.cell(row)}</span>
                </div>
              ))}
            {actionNodes ? (
              <div className="relative z-10 flex flex-wrap justify-end gap-2 border-t pt-3">{actionNodes}</div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
