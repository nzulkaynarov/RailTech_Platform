/**
 * Страница реестра обнуляется В ТОМ ЖЕ коммите, что и смена выборки.
 *
 * Дефект (найден триажем правил React Compiler 18-08): сброс делал `useEffect` ПОСЛЕ коммита,
 * поэтому у реестров с серверной постраничкой (MyProductsPage, ProductManagement) успевал уйти
 * запрос с новым фильтром и СТАРОЙ страницей: человек видел кадр «Ничего не найдено», а потом
 * летел второй запрос уже с page=1 — два похода в бэкенд на каждую смену поиска/фильтра/сортировки.
 *
 * Тест смотрит на состояние ПОСЛЕ одного `act`: если сброс снова уедет в эффект, здесь останется
 * старая страница на одном из промежуточных кадров.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

import { useListParams } from '../listParams';

describe('useListParams — сброс страницы при смене выборки', () => {
  it('смена фильтра обнуляет страницу вместе с фильтром', () => {
    const { result } = renderHook(() => useListParams(['status']));

    act(() => result.current.setPage(3));
    expect(result.current.page).toBe(3);

    act(() => result.current.setFilter('status', 'active'));
    expect(result.current.filters.status).toBe('active');
    expect(result.current.page).toBe(1);
  });

  it('смена сортировки обнуляет страницу', () => {
    const { result } = renderHook(() => useListParams([], { defaultOrdering: 'name' }));

    act(() => result.current.setPage(5));
    act(() => result.current.toggleOrdering('created_at'));

    expect(result.current.ordering).toBe('created_at');
    expect(result.current.page).toBe(1);
  });

  it('поиск (после дебаунса) применяется вместе со сбросом страницы', () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useListParams([], { debounceMs: 300 }));

      act(() => result.current.setPage(4));
      act(() => result.current.setSearchInput('рельс'));
      // До истечения дебаунса ничего не поменялось: запрос ещё не ушёл.
      expect(result.current.search).toBe('');
      expect(result.current.page).toBe(4);

      act(() => vi.advanceTimersByTime(300));
      expect(result.current.search).toBe('рельс');
      expect(result.current.page).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('переход по страницам не сбрасывает саму страницу', () => {
    const { result } = renderHook(() => useListParams([]));
    act(() => result.current.setPage(2));
    expect(result.current.page).toBe(2);
  });
});

beforeEach(() => vi.clearAllTimers());
afterEach(() => vi.useRealTimers());
