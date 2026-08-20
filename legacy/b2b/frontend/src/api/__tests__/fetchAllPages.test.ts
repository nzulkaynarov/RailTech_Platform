import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/api/client', () => ({ apiClient: { get: vi.fn() } }));

import { apiClient } from '@/api/client';
import { fetchAllPages, MAX_PAGE_SIZE } from '@/api/fetchAllPages';

const mockedGet = vi.mocked(apiClient.get);

/**
 * Реестры оператора печатают счётчики вкладок и «Всего» по этому же списку и пейджера не имеют:
 * взять первую страницу — значит показать 20 записей из 42 и счётчики по этим же двадцати. Обход
 * жил ТРЕМЯ копиями, теперь один — и он должен реально листать, а не «работать», пока страница
 * ровно одна.
 */
describe('fetchAllPages', () => {
  beforeEach(() => mockedGet.mockReset());

  it('листает все страницы, а не только первую', async () => {
    mockedGet
      .mockResolvedValueOnce({
        data: { results: [{ id: 1 }, { id: 2 }], next: 'https://host/api/v1/accounts/companies/?page=2', count: 3 },
      } as never)
      .mockResolvedValueOnce({ data: { results: [{ id: 3 }], next: null, count: 3 } } as never);

    const rows = await fetchAllPages<{ id: number }>('accounts/companies/');

    expect(rows.map((r) => r.id)).toEqual([1, 2, 3]);
    expect(mockedGet).toHaveBeenCalledTimes(2);
  });

  it('просит максимальный размер страницы — один запрос вместо десяти', async () => {
    mockedGet.mockResolvedValueOnce({ data: { results: [], next: null, count: 0 } } as never);

    await fetchAllPages('accounts/companies/', { status: 'ACTIVE' });

    expect(mockedGet).toHaveBeenCalledWith('accounts/companies/', {
      params: { status: 'ACTIVE', page_size: MAX_PAGE_SIZE },
    });
  });

  it('не повторяет фильтры во втором запросе — ссылка next несёт их сама', async () => {
    mockedGet
      .mockResolvedValueOnce({
        data: { results: [{ id: 1 }], next: 'https://host/api/v1/accounts/companies/?page=2&status=ACTIVE', count: 2 },
      } as never)
      .mockResolvedValueOnce({ data: { results: [{ id: 2 }], next: null, count: 2 } } as never);

    await fetchAllPages('accounts/companies/', { status: 'ACTIVE' });

    expect(mockedGet).toHaveBeenNthCalledWith(2, 'accounts/companies/?page=2&status=ACTIVE', {});
  });

  it('обрывает бесконечную цепочку next, а не вешает вкладку', async () => {
    mockedGet.mockResolvedValue({
      data: { results: [{ id: 1 }], next: 'https://host/api/v1/accounts/companies/?page=2', count: 99999 },
    } as never);

    const rows = await fetchAllPages('accounts/companies/');

    expect(mockedGet.mock.calls.length).toBeLessThanOrEqual(500);
    expect(rows.length).toBeLessThanOrEqual(500);
  });
});
