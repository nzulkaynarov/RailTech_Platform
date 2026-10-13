import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';

import { AdminDataTable, type AdminTableColumn, type AdminTableBulkAction } from '../AdminDataTable';
import { renderWithProviders } from '@/test/renderWithProviders';

interface UserRow {
  id: number;
  name: string;
  status: string;
}

const ROWS: UserRow[] = [
  { id: 1, name: 'Alpha LLC', status: 'ACTIVE' },
  { id: 2, name: 'Beta GmbH', status: 'BLOCKED' },
  { id: 3, name: 'Gamma JSC', status: 'ACTIVE' },
];

const COLUMNS: AdminTableColumn<UserRow>[] = [
  { id: 'name', header: 'Название', alwaysVisible: true },
  { id: 'status', header: 'Статус', sortKey: 'status' },
];

function getRowByText(text: string): HTMLElement {
  const rowEl = screen.getByText(text).closest('tr');
  if (!rowEl) throw new Error(`No <tr> found containing "${text}"`);
  return rowEl;
}

describe('AdminDataTable', () => {
  beforeEach(() => {
    // Table state persists in URL query params + localStorage — reset both between tests.
    window.history.replaceState(null, '', '/');
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders one row per data item with cell values', () => {
    renderWithProviders(
      <AdminDataTable storageKey="users" rows={ROWS} getRowId={(r) => r.id} columns={COLUMNS} />,
    );

    expect(screen.getByText('Alpha LLC')).toBeInTheDocument();
    expect(screen.getByText('Beta GmbH')).toBeInTheDocument();
    expect(screen.getByText('Gamma JSC')).toBeInTheDocument();
    // header row + 3 data rows
    expect(screen.getAllByRole('row')).toHaveLength(4);
  });

  it('shows the default localized empty state when there are no rows', () => {
    renderWithProviders(
      <AdminDataTable storageKey="users" rows={[]} getRowId={(r: UserRow) => r.id} columns={COLUMNS} />,
    );

    // adminTable.empty resolved from the real ru.json
    expect(screen.getByText('Записей нет')).toBeInTheDocument();
  });

  it('shows skeleton rows (not the empty state) while loading', () => {
    renderWithProviders(
      <AdminDataTable
        storageKey="users"
        rows={[]}
        getRowId={(r: UserRow) => r.id}
        columns={COLUMNS}
        isLoading
      />,
    );

    expect(screen.queryByText('Записей нет')).not.toBeInTheDocument();
    // header row + 5 skeleton rows
    expect(screen.getAllByRole('row')).toHaveLength(6);
  });

  describe('row activation (PR #229 keyboard a11y)', () => {
    it('marks clickable rows as focusable buttons', () => {
      renderWithProviders(
        <AdminDataTable
          storageKey="users"
          rows={ROWS}
          getRowId={(r) => r.id}
          columns={COLUMNS}
          onRowClick={vi.fn()}
        />,
      );

      const row = getRowByText('Alpha LLC');
      expect(row).toHaveAttribute('role', 'button');
      expect(row).toHaveAttribute('tabindex', '0');
    });

    it('does not add role/tabindex when rows are not clickable', () => {
      renderWithProviders(
        <AdminDataTable storageKey="users" rows={ROWS} getRowId={(r) => r.id} columns={COLUMNS} />,
      );

      const row = getRowByText('Alpha LLC');
      expect(row).not.toHaveAttribute('role');
      expect(row).not.toHaveAttribute('tabindex');
    });

    it('activates the row on click', () => {
      const onRowClick = vi.fn();
      renderWithProviders(
        <AdminDataTable
          storageKey="users"
          rows={ROWS}
          getRowId={(r) => r.id}
          columns={COLUMNS}
          onRowClick={onRowClick}
        />,
      );

      fireEvent.click(screen.getByText('Beta GmbH'));
      expect(onRowClick).toHaveBeenCalledTimes(1);
      expect(onRowClick).toHaveBeenCalledWith(ROWS[1]);
    });

    it('activates the focused row on Enter and Space', () => {
      const onRowClick = vi.fn();
      renderWithProviders(
        <AdminDataTable
          storageKey="users"
          rows={ROWS}
          getRowId={(r) => r.id}
          columns={COLUMNS}
          onRowClick={onRowClick}
        />,
      );

      const row = getRowByText('Alpha LLC');
      row.focus();
      fireEvent.keyDown(row, { key: 'Enter' });
      expect(onRowClick).toHaveBeenCalledTimes(1);
      expect(onRowClick).toHaveBeenLastCalledWith(ROWS[0]);

      fireEvent.keyDown(row, { key: ' ' });
      expect(onRowClick).toHaveBeenCalledTimes(2);
    });

    it('does not activate when the keydown originates from a nested control', () => {
      const onRowClick = vi.fn();
      renderWithProviders(
        <AdminDataTable
          storageKey="users"
          rows={ROWS}
          getRowId={(r) => r.id}
          columns={COLUMNS}
          onRowClick={onRowClick}
        />,
      );

      // Keydown target = the cell, not the row itself → guard must ignore it.
      fireEvent.keyDown(screen.getByText('Alpha LLC'), { key: 'Enter' });
      expect(onRowClick).not.toHaveBeenCalled();
    });

    it('supports j/k focus navigation + Enter to open (global shortcuts)', () => {
      const onRowClick = vi.fn();
      renderWithProviders(
        <AdminDataTable
          storageKey="users"
          rows={ROWS}
          getRowId={(r) => r.id}
          columns={COLUMNS}
          onRowClick={onRowClick}
        />,
      );

      // j, j → focus moves to the second row; Enter opens it.
      fireEvent.keyDown(window, { key: 'j' });
      fireEvent.keyDown(window, { key: 'j' });
      expect(getRowByText('Beta GmbH')).toHaveAttribute('data-focused', 'true');

      fireEvent.keyDown(window, { key: 'Enter' });
      expect(onRowClick).toHaveBeenCalledWith(ROWS[1]);

      // k → focus moves back up to the first row.
      fireEvent.keyDown(window, { key: 'k' });
      expect(getRowByText('Alpha LLC')).toHaveAttribute('data-focused', 'true');
    });
  });

  describe('selection + bulk actions', () => {
    it('selects a row via checkbox without triggering row click, runs the bulk action, then clears', async () => {
      const onRowClick = vi.fn();
      const onRun = vi.fn().mockResolvedValue(undefined);
      const bulkActions: AdminTableBulkAction<UserRow>[] = [
        { id: 'block', label: 'Заблокировать', onRun },
      ];
      renderWithProviders(
        <AdminDataTable
          storageKey="users"
          rows={ROWS}
          getRowId={(r) => r.id}
          columns={COLUMNS}
          bulkActions={bulkActions}
          onRowClick={onRowClick}
        />,
      );

      // adminTable.selectRow resolved from ru.json
      const rowCheckboxes = screen.getAllByRole('checkbox', { name: 'Выбрать строку' });
      expect(rowCheckboxes).toHaveLength(3);

      fireEvent.click(rowCheckboxes[0]);
      // Checkbox interaction must NOT bubble into row activation.
      expect(onRowClick).not.toHaveBeenCalled();
      // Bulk toolbar appears with the localized selection counter.
      expect(screen.getByText('Выбрано: 1')).toBeInTheDocument();

      fireEvent.click(rowCheckboxes[2]);
      expect(screen.getByText('Выбрано: 2')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'Заблокировать' }));
      await waitFor(() => expect(onRun).toHaveBeenCalledWith([ROWS[0], ROWS[2]]));
      // Selection is cleared after a successful bulk run → toolbar disappears.
      await waitFor(() => expect(screen.queryByText(/Выбрано/)).not.toBeInTheDocument());
    });

    it('select-all checkbox toggles the whole page', () => {
      const bulkActions: AdminTableBulkAction<UserRow>[] = [
        { id: 'noop', label: 'Действие', onRun: vi.fn() },
      ];
      renderWithProviders(
        <AdminDataTable
          storageKey="users"
          rows={ROWS}
          getRowId={(r) => r.id}
          columns={COLUMNS}
          bulkActions={bulkActions}
        />,
      );

      fireEvent.click(screen.getByRole('checkbox', { name: 'Выбрать все' }));
      expect(screen.getByText('Выбрано: 3')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('checkbox', { name: 'Выбрать все' }));
      expect(screen.queryByText(/Выбрано/)).not.toBeInTheDocument();
    });
  });

  it('debounces search input into a namespaced URL query param', () => {
    vi.useFakeTimers();
    renderWithProviders(
      <AdminDataTable storageKey="users" rows={ROWS} getRowId={(r) => r.id} columns={COLUMNS} />,
    );

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'alpha' } });
    // Not yet — debounced by 300ms.
    expect(new URLSearchParams(window.location.search).get('users.q')).toBeNull();

    act(() => {
      vi.advanceTimersByTime(350);
    });
    expect(new URLSearchParams(window.location.search).get('users.q')).toBe('alpha');
  });

  it('toggles column sort asc → desc via the namespaced URL param', () => {
    renderWithProviders(
      <AdminDataTable storageKey="users" rows={ROWS} getRowId={(r) => r.id} columns={COLUMNS} />,
    );

    const statusHeader = screen.getByRole('columnheader', { name: 'Статус' });
    fireEvent.click(statusHeader);
    expect(new URLSearchParams(window.location.search).get('users.sort')).toBe('status');

    fireEvent.click(statusHeader);
    expect(new URLSearchParams(window.location.search).get('users.sort')).toBe('-status');
  });

  it('renders pagination with localized range label and pages forward', () => {
    const onPageChange = vi.fn();
    renderWithProviders(
      <AdminDataTable
        storageKey="users"
        rows={ROWS}
        getRowId={(r) => r.id}
        columns={COLUMNS}
        pagination={{ total: 50, page: 1, pageSize: 20, onPageChange }}
      />,
    );

    // adminTable.paginationLabel with interpolation, from the real ru.json
    expect(screen.getByText('1–20 из 50')).toBeInTheDocument();
    // On page 1 the "prev" button is disabled.
    expect(screen.getByRole('button', { name: 'Назад' })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
    expect(onPageChange).toHaveBeenCalledWith(2);
    expect(new URLSearchParams(window.location.search).get('users.page')).toBe('2');
  });
});
