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

/** Порядок ядра — публичная константа: на неё опирается guard-тест единообразия реестров. */
