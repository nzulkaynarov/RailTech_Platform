import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useListParams } from '../listParams';

/**
 * Состояние списка адресуемо (находка 81 прогона 20-08, замер 26-08).
 *
 * Поиск, фильтры, сортировка и страница жили только в памяти компонента: F5 сбрасывал их, а
 * ссылка, посланная коллеге, открывала не тот экран, что видел отправитель. Соседние
 * операторские реестры состояние в адрес пишут — расхождение было внутреннее.
 *
 * Ключ обязателен как ПРОСТРАНСТВО ИМЁН: на одном экране бывает несколько списков, и без
 * разделения они затирали бы состояние друг друга.
 */

const setUrl = (search: string) => {
  window.history.replaceState({}, '', search ? `/?${search}` : '/');
};

beforeEach(() => setUrl(''));
afterEach(() => setUrl(''));

describe('состояние списка в адресе', () => {
  it('без ключа адрес не трогается — поведение прежнее', () => {
    const { result } = renderHook(() => useListParams([]));

    act(() => result.current.setSearchInput('насос'));

    expect(window.location.search).toBe('');
  });

  it('поиск попадает в адрес под своим пространством имён', async () => {
    const { result } = renderHook(() => useListParams([], { urlKey: 'deals', debounceMs: 0 }));

    act(() => result.current.setSearchInput('насос'));

    // `waitFor`, а не фиксированная пауза: между вводом и записью в адрес стоят устранение
    // дребезга и коммит эффекта, и жёсткий таймаут делает тест ложно-красным на медленной
    // машине — то есть проверкой скорости, а не поведения.
    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get('deals.q')).toBe('насос');
    });
  });

  it('состояние читается из адреса при монтировании — F5 и ссылка коллеге переживают', () => {
    setUrl('deals.q=%D0%BD%D0%B0%D1%81%D0%BE%D1%81&deals.f_stage=RFQ_OPEN&deals.page=3');

    const { result } = renderHook(() => useListParams(['stage'] as const, { urlKey: 'deals' }));

    expect(result.current.search).toBe('насос');
    expect(result.current.filters.stage).toBe('RFQ_OPEN');
    expect(result.current.page).toBe(3);
  });

  it('чужое пространство имён не читается', () => {
    setUrl('quotes.q=%D1%87%D1%83%D0%B6%D0%BE%D0%B5');

    const { result } = renderHook(() => useListParams([], { urlKey: 'deals' }));

    expect(result.current.search).toBe('');
  });

  it('значения по умолчанию в адрес не пишутся — ссылка остаётся читаемой', async () => {
    const { result } = renderHook(() =>
      useListParams(['stage'] as const, { urlKey: 'deals', defaultOrdering: '-created_at', debounceMs: 0 }),
    );

    act(() => result.current.setFilter('stage', 'all'));

    await waitFor(() => expect(window.location.search).toBe(''));
  });

  it('сброс поиска убирает параметр, а не оставляет пустой', async () => {
    const { result } = renderHook(() => useListParams([], { urlKey: 'deals', debounceMs: 0 }));

    act(() => result.current.setSearchInput('насос'));
    await waitFor(() => expect(window.location.search).not.toBe(''));

    act(() => result.current.setSearchInput(''));

    await waitFor(() => expect(window.location.search).toBe(''));
  });
});
