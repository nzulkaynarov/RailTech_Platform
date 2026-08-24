import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';

vi.mock('@/lib/download', () => ({ downloadFile: vi.fn().mockResolvedValue(undefined) }));

import { downloadFile } from '@/lib/download';
import { AdminDataTable, type AdminTableColumn } from '../AdminDataTable';
import { renderWithProviders } from '@/test/renderWithProviders';

/**
 * Кнопка «Экспорт» открывала НОВУЮ ВКЛАДКУ через `window.open`.
 *
 * На `/api/v1/` чистый JWT и никаких сессий: вкладка уходит без заголовка `Authorization`,
 * получает 401 и показывает человеку пустую вкладку приложения вместо файла. Выгрузка была
 * мертва на всех четырёх операторских реестрах, и обходного пути в интерфейсе нет (прогон 20-08).
 *
 * Тест мерит ровно это: запрос уходит АВТОРИЗОВАННЫМ путём и вкладок никто не открывает.
 */

interface Row { id: number; name: string }
const ROWS: Row[] = [{ id: 1, name: 'Alpha LLC' }];
const COLUMNS: AdminTableColumn<Row>[] = [{ id: 'name', header: 'Название', alwaysVisible: true }];

function renderTable(extra: Record<string, unknown> = {}) {
  return renderWithProviders(
    <AdminDataTable<Row>
      rows={ROWS}
      columns={COLUMNS}
      getRowId={(r) => r.id}
      storageKey="exportTest"
      exportUrl={`${window.location.origin}/api/v1/accounts/companies/export/`}
      {...extra}
    />,
  );
}

async function clickExport(format: RegExp) {
  // Radix DropdownMenu не открывается от `click()` в jsdom — он слушает указатель и
  // клавиатуру. Клавиатурный путь надёжнее и заодно проверяет доступность меню.
  const trigger = screen.getByRole('button', { name: /export|экспорт/i });
  trigger.focus();
  fireEvent.keyDown(trigger, { key: 'Enter' });
  const item = await screen.findByText(format);
  fireEvent.click(item);
}

describe('Выгрузка операторского реестра', () => {
  beforeEach(() => {
    vi.mocked(downloadFile).mockClear();
    vi.spyOn(window, 'open').mockImplementation(() => null);
  });

  it('скачивает файл авторизованным запросом, а не открывает вкладку', async () => {
    renderTable();

    await clickExport(/csv/i);

    await waitFor(() => expect(downloadFile).toHaveBeenCalledTimes(1));
    expect(window.open).not.toHaveBeenCalled();
  });

  it('запрашивает ОТНОСИТЕЛЬНЫЙ путь — иначе перехватчик токена не сработает', async () => {
    renderTable();

    await clickExport(/csv/i);

    await waitFor(() => expect(downloadFile).toHaveBeenCalled());
    const [path] = vi.mocked(downloadFile).mock.calls[0];
    expect(path.startsWith('http')).toBe(false);
    expect(path).toContain('accounts/companies/export/');
    expect(path).toContain('fmt=csv');
  });

  it('даёт файлу осмысленное имя: у blob-ссылки нет Content-Disposition от сервера', async () => {
    renderTable();

    await clickExport(/xlsx/i);

    await waitFor(() => expect(downloadFile).toHaveBeenCalled());
    const [, filename] = vi.mocked(downloadFile).mock.calls[0];
    expect(filename).toMatch(/^companies-\d{4}-\d{2}-\d{2}\.xlsx$/);
  });

  it('переносит в выгрузку активный поиск — файл должен совпадать с тем, что на экране', async () => {
    // Поиск уходит в адрес с задержкой (та же, после которой перефильтровывается таблица),
    // поэтому ждём её: иначе тест мерил бы момент ДО применения поиска и проходил бы
    // одинаково и на работающем коде, и на сломанном.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderTable();
      const search = screen.getByPlaceholderText(/search|поиск/i);
      fireEvent.change(search, { target: { value: 'Alpha' } });
      await act(async () => {
        vi.advanceTimersByTime(600);
      });

      await clickExport(/csv/i);

      await waitFor(() => expect(downloadFile).toHaveBeenCalled());
      expect(vi.mocked(downloadFile).mock.calls[0][0]).toContain('search=Alpha');
    } finally {
      vi.useRealTimers();
    }
  });
});
