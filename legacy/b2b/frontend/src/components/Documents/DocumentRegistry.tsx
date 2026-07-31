/**
 * Один каркас для всех реестров документов.
 *
 * Шесть реестров (договоры, счета, акты, платежи, отгрузки, произвольные) были написаны шестью
 * способами: четыре на сыром `Table`, один на `ResponsiveDataTable`, отгрузки — своей вёрсткой;
 * у одних действия в `DocumentActions`, у других сырые кнопки; у одних карточка, у других нет;
 * наборы и порядок колонок у каждого свои. Пользователь, освоив первый реестр, не мог перенести
 * этот опыт на второй (наблюдение владельца 2026-07-31).
 *
 * Эталон — Salesforce Lightning Design System: единый набор компонентов даёт «consistent patterns
 * for user interactions across the app», а список поддерживает фиксированный набор стандартных
 * действий. В Odoo у всех моделей одна пара «list view + form view». Смысл один: **увидев один
 * реестр, человек знает, как устроены остальные.**
 *
 * Конвенция репозитория этого уже требовала («новые списки — через `ResponsiveDataTable`»);
 * компонент не вводит новое правило, а делает его выполнимым в одну строку.
 */
import { type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Card, CardContent } from '@/components/ui/card';
import { Pager } from '@/components/DataTable';
import { ResponsiveDataTable, type ResponsiveColumn } from '@/components/ResponsiveDataTable';
import { EmptyState, ErrorState, LoadingRows } from '@/pages/shared/PageShell';

export interface DocumentRegistryProps<T> {
  rows: T[];
  getRowId: (row: T) => string | number;
  columns: ResponsiveColumn<T>[];
  /** Клик по строке открывает карточку документа — во всех реестрах одинаково. */
  onRowClick?: (row: T) => void;
  /** Панель фильтров конкретного реестра (поиск, статус) — рендерится над таблицей. */
  toolbar?: ReactNode;
  isLoading?: boolean;
  isError?: boolean;
  onRetry?: () => void;
  /** Пустое состояние: своя иконка и подпись у каждого типа документа. */
  emptyIcon: ReactNode;
  emptyMessage: string;
  emptyHint?: string;
  sorting?: { ordering: string; onToggle: (key: string) => void };
  pagination?: { page: number; pageSize: number; total: number; onPageChange: (page: number) => void };
}

export function DocumentRegistry<T>({
  rows,
  getRowId,
  columns,
  onRowClick,
  toolbar,
  isLoading,
  isError,
  onRetry,
  emptyIcon,
  emptyMessage,
  emptyHint,
  sorting,
  pagination,
}: DocumentRegistryProps<T>) {
  return (
    <Card>
      <CardContent className="p-0">
        {toolbar}
        {/* Три состояния разведены во ВСЕХ реестрах одинаково (волна U2): загрузка, сбой и
            пустота — разные вещи, и ни одна из них не должна выглядеть как другая. */}
        {isLoading ? (
          <LoadingRows rows={5} />
        ) : isError ? (
          <ErrorState onRetry={onRetry} />
        ) : rows.length === 0 ? (
          <EmptyState icon={emptyIcon} message={emptyMessage} hint={emptyHint} />
        ) : (
          <>
            <ResponsiveDataTable
              columns={columns}
              rows={rows}
              getRowId={getRowId}
              onRowClick={onRowClick}
              sorting={sorting}
            />
            {pagination ? (
              <Pager
                page={pagination.page}
                pageSize={pagination.pageSize}
                total={pagination.total}
                onPageChange={pagination.onPageChange}
              />
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * Ядро колонок документа в ФИКСИРОВАННОМ порядке: номер → сделка → статус → сумма → дата →
 * действия. Порядок и подписи одни на все реестры — именно их разнобой и делал реестры
 * непохожими друг на друга. Специфические колонки (срок оплаты у счёта, сторона у договора)
 * добавляются вокруг ядра, а не вместо него.
 *
 * Колонка пропускается, если её не передали: у платежа нет статуса, у отгрузки — суммы.
 */
export interface DocumentCoreCells<T> {
  number?: (row: T) => ReactNode;
  deal?: (row: T) => ReactNode;
  status?: (row: T) => ReactNode;
  total?: (row: T) => ReactNode;
  date?: (row: T) => ReactNode;
  actions?: (row: T) => ReactNode;
  /** Ключи сортировки, если реестр её поддерживает. */
  sortKeys?: { number?: string; total?: string; date?: string };
  /** Подпись колонки даты: «Выставлен», «Создан», «Оплачен» — смысл у каждого документа свой. */
  dateHeader?: string;
  /**
   * Колонки, специфичные для типа документа (оплачено у счёта, сторона у договора), — ВОКРУГ
   * ядра, а не вместо него: ядро остаётся на своих местах во всех реестрах, а особенное
   * приставляется к понятному якорю.
   */
  insertAfter?: Partial<Record<(typeof DOCUMENT_CORE_COLUMN_ORDER)[number], ResponsiveColumn<never>[]>>;
}

export function useDocumentCoreColumns<T>(cells: DocumentCoreCells<T>): ResponsiveColumn<T>[] {
  const { t } = useTranslation();
  const columns: ResponsiveColumn<T>[] = [];
  const extrasAfter = (anchor: (typeof DOCUMENT_CORE_COLUMN_ORDER)[number]) => {
    for (const extra of (cells.insertAfter?.[anchor] ?? []) as ResponsiveColumn<T>[]) {
      columns.push(extra);
    }
  };

  if (cells.number) {
    columns.push({
      id: 'number',
      header: t('documentRegistry.columns.number'),
      sortKey: cells.sortKeys?.number,
      mobileTitle: true,
      cell: cells.number,
    });
    extrasAfter('number');
  }
  if (cells.deal) {
    columns.push({ id: 'deal', header: t('documentRegistry.columns.deal'), cell: cells.deal });
    extrasAfter('deal');
  }
  if (cells.status) {
    columns.push({ id: 'status', header: t('documentRegistry.columns.status'), cell: cells.status });
    extrasAfter('status');
  }
  if (cells.total) {
    columns.push({
      id: 'total',
      header: t('documentRegistry.columns.total'),
      sortKey: cells.sortKeys?.total,
      className: 'text-right',
      cell: cells.total,
    });
    extrasAfter('total');
  }
  if (cells.date) {
    columns.push({
      id: 'date',
      header: cells.dateHeader ?? t('documentRegistry.columns.date'),
      sortKey: cells.sortKeys?.date,
      className: 'text-xs text-muted-foreground',
      cell: cells.date,
    });
    extrasAfter('date');
  }
  if (cells.actions) {
    columns.push({
      id: 'actions',
      header: t('documentRegistry.columns.actions'),
      className: 'text-right',
      mobileActions: true,
      cell: cells.actions,
    });
    extrasAfter('actions');
  }
  return columns;
}

/** Порядок ядра — публичная константа: на неё опирается guard-тест единообразия реестров. */
export const DOCUMENT_CORE_COLUMN_ORDER = ['number', 'deal', 'status', 'total', 'date', 'actions'] as const;
