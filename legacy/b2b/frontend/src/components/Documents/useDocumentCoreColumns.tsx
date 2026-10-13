/**
 * Общие колонки реестров документов. Отдельный модуль — Fast Refresh: файл с компонентом
 * `DocumentRegistry` не должен экспортировать ещё и хук.
 */

import { useTranslation } from 'react-i18next';
import type { ReactNode } from 'react';
import type { ResponsiveColumn } from '@/components/ResponsiveDataTable';

export const DOCUMENT_CORE_COLUMN_ORDER = ['number', 'deal', 'status', 'total', 'date', 'actions'] as const;

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
