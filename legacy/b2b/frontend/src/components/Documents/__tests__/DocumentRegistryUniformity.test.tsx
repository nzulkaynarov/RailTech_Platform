/**
 * Инвариант волны D2: **реестры документов выглядят одинаково.**
 *
 * Шесть реестров были написаны шестью способами — четыре на сыром `Table`, один на
 * `ResponsiveDataTable`, отгрузки своей вёрсткой; у одних действия в `DocumentActions`, у других
 * сырые кнопки; наборы и порядок колонок у каждого свои. Пользователь, освоив первый реестр, не
 * мог перенести опыт на второй (наблюдение владельца 2026-07-31).
 *
 * Эталон — Salesforce Lightning Design System и Odoo: один компонент списка на все объекты даёт
 * предсказуемость. Тест держит именно её: порядок ядра колонок и разведённые состояния.
 */

import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import { DocumentRegistry } from '../DocumentRegistry';
import { useDocumentCoreColumns, DOCUMENT_CORE_COLUMN_ORDER } from '../useDocumentCoreColumns';

interface Row { id: number; number: string }

const ROWS: Row[] = [{ id: 1, number: 'DOC-1' }];

/** Тестовый потребитель: собирает ядро так же, как это делает страница реестра. */
function Harness({ withExtras = false, ...registryProps }: { withExtras?: boolean } & Record<string, unknown>) {
  const columns = useDocumentCoreColumns<Row>({
    number: (row) => row.number,
    deal: () => '42',
    status: () => 'ISSUED',
    total: () => '112',
    date: () => '01.07.2026',
    actions: () => 'PDF',
    insertAfter: withExtras
      ? { total: [{ id: 'paid', header: 'Оплачено', cell: () => '0' }] }
      : undefined,
  });
  return (
    <DocumentRegistry
      rows={ROWS}
      getRowId={(row: Row) => row.id}
      columns={columns}
      emptyIcon={null}
      emptyMessage="пусто"
      {...registryProps}
    />
  );
}

function renderHarness(props: Record<string, unknown> = {}) {
  return renderWithProviders(<Harness {...props} />);
}

/** Заголовки таблицы в порядке отображения (десктопная часть `ResponsiveDataTable`). */
function headerTexts(): string[] {
  return Array.from(document.querySelectorAll('thead th')).map((th) => th.textContent?.trim() ?? '');
}

describe('единый вид реестров документов', () => {
  it('ядро колонок идёт в фиксированном порядке', () => {
    renderHarness();

    const expected = ['Номер', 'Сделка', 'Статус', 'Сумма', 'Дата', 'Действия'];
    expect(headerTexts()).toEqual(expected);
    // Порядок объявлен константой — тест и компонент опираются на один источник.
    expect(DOCUMENT_CORE_COLUMN_ORDER).toEqual(['number', 'deal', 'status', 'total', 'date', 'actions']);
  });

  it('колонки конкретного документа приставляются ВОКРУГ ядра, не вместо него', () => {
    renderHarness({ withExtras: true });

    // «Оплачено» встало после суммы; ядро осталось на своих местах.
    expect(headerTexts()).toEqual(['Номер', 'Сделка', 'Статус', 'Сумма', 'Оплачено', 'Дата', 'Действия']);
  });

  it('загрузка, сбой и пустота — три РАЗНЫХ состояния', () => {
    const { unmount } = renderHarness({ isLoading: true });
    expect(document.querySelectorAll('thead th')).toHaveLength(0);
    unmount();

    const retry = vi.fn();
    const errorView = renderHarness({ isError: true, onRetry: retry });
    expect(screen.getByText('Не удалось загрузить данные')).toBeInTheDocument();
    errorView.unmount();

    renderWithProviders(
      <DocumentRegistry
        rows={[]}
        getRowId={(row: Row) => row.id}
        columns={[]}
        emptyIcon={null}
        emptyMessage="Документов нет"
      />,
    );
    expect(screen.getByText('Документов нет')).toBeInTheDocument();
    // Пустота НЕ выглядит как ошибка — это разные утверждения (волна U2).
    expect(screen.queryByText('Не удалось загрузить данные')).not.toBeInTheDocument();
  });
});
